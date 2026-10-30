\set ON_ERROR_STOP on
-- ===========================================================================
-- DensaMed — Deliverable C: inventory-control addendum
-- Target database : densamed   (NEVER run against the odoo database)
-- Idempotent      : safe to re-run any number of times.
-- Apply manually  : docker compose exec -T db psql -v ON_ERROR_STOP=1 \
--                     -U "$POSTGRES_USER" -d densamed -f /sql/99-inventory-control.sql
-- ===========================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1) storage_locations — physical hierarchy inside a warehouse
--    zone -> aisle -> shelf -> bin, self-referencing tree.
--    NOTE: this file is also loaded at first boot (30-densamed-addenda.sh), so
--    the table may already exist; everything below is IF-NOT-EXISTS-safe.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.storage_locations (
    location_id   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    warehouse_id  BIGINT NOT NULL REFERENCES public.warehouses(warehouse_id) ON DELETE CASCADE,
    parent_id     BIGINT REFERENCES public.storage_locations(location_id) ON DELETE CASCADE,
    location_code VARCHAR(40) NOT NULL,
    location_type VARCHAR(20) NOT NULL DEFAULT 'bin'
        CHECK (location_type IN ('zone','aisle','shelf','bin')),
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (warehouse_id, location_code)
);

CREATE INDEX IF NOT EXISTS idx_storage_locations_warehouse
    ON public.storage_locations(warehouse_id);
CREATE INDEX IF NOT EXISTS idx_storage_locations_parent
    ON public.storage_locations(parent_id);

-- Case-insensitive uniqueness: staff key codes by hand ('A-1' vs 'a-1').
CREATE UNIQUE INDEX IF NOT EXISTS uq_storage_locations_wh_code_ci
    ON public.storage_locations(warehouse_id, lower(location_code));

-- Cycle guard: walk the parent chain and reject any location that is its own ancestor.
CREATE OR REPLACE FUNCTION public.assert_location_no_cycle() RETURNS TRIGGER
LANGUAGE plpgsql AS $fn$
DECLARE
    v_id BIGINT := NEW.parent_id;
    v_depth INTEGER := 0;
BEGIN
    WHILE v_id IS NOT NULL LOOP
        IF v_id = NEW.location_id THEN
            RAISE EXCEPTION 'storage_locations cycle detected at location %', NEW.location_id;
        END IF;
        SELECT parent_id INTO v_id FROM public.storage_locations WHERE location_id = v_id;
        v_depth := v_depth + 1;
        IF v_depth > 32 THEN                      -- tree depth cap: zone/aisle/shelf/bin = 4
            RAISE EXCEPTION 'storage_locations hierarchy deeper than 32 levels (location %)', NEW.location_id;
        END IF;
    END LOOP;
    RETURN NEW;
END;
$fn$;

DROP TRIGGER IF EXISTS trg_location_no_cycle ON public.storage_locations;
CREATE CONSTRAINT TRIGGER trg_location_no_cycle
    AFTER INSERT OR UPDATE OF parent_id ON public.storage_locations
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION public.assert_location_no_cycle();

COMMENT ON TABLE public.storage_locations IS
    'Physical WMS hierarchy per warehouse (zone/aisle/shelf/bin); mirrored to stock.location by densamed_bridge.';

-- ---------------------------------------------------------------------------
-- 2) stock_movements — immutable append-only audit trail.
--    Every balance change in inventory MUST come from a row inserted here;
--    the AFTER INSERT trigger maintains inventory.quantity_on_hand.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.stock_movements (
    movement_id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    movement_type     VARCHAR(20) NOT NULL
        CHECK (movement_type IN ('receipt','issue','transfer','adjustment','return')),
    medicine_id       BIGINT NOT NULL REFERENCES public.medicines(medicine_id),
    batch_id          BIGINT NOT NULL REFERENCES public.medicine_batches(batch_id),
    from_warehouse_id BIGINT REFERENCES public.warehouses(warehouse_id),
    from_location_id  BIGINT REFERENCES public.storage_locations(location_id),
    to_warehouse_id   BIGINT REFERENCES public.warehouses(warehouse_id),
    to_location_id    BIGINT REFERENCES public.storage_locations(location_id),
    quantity          INTEGER NOT NULL CHECK (quantity > 0),
    reference_type    VARCHAR(24),          -- e.g. 'purchase_receipt', 'sale', 'manual'
    reference_id      BIGINT,               -- FK intentionally polymorphic (no cross-table FK)
    performed_by      BIGINT REFERENCES public.employees(employee_id),
    performed_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- every movement needs at least one side
    CHECK (from_warehouse_id IS NOT NULL OR to_warehouse_id IS NOT NULL),
    -- a location always sits inside the warehouse of its column
    CHECK (from_location_id IS NULL OR from_warehouse_id IS NOT NULL),
    CHECK (to_location_id   IS NULL OR to_warehouse_id   IS NOT NULL),
    -- transfers need two distinct endpoints
    CHECK (from_warehouse_id IS NULL OR to_warehouse_id IS NULL
           OR from_warehouse_id <> to_warehouse_id)
);

CREATE INDEX IF NOT EXISTS idx_movements_batch_time
    ON public.stock_movements(batch_id, performed_at);
CREATE INDEX IF NOT EXISTS idx_movements_medicine
    ON public.stock_movements(medicine_id, performed_at);
CREATE INDEX IF NOT EXISTS idx_movements_to_wh
    ON public.stock_movements(to_warehouse_id, performed_at);

COMMENT ON TABLE public.stock_movements IS
    'Append-only audit trail; inventory.quantity_on_hand is derived exclusively from this table.';

-- ---------------------------------------------------------------------------
-- 3) inventory — derived balance table + trigger maintaining quantity_on_hand
-- ---------------------------------------------------------------------------
ALTER TABLE public.inventory
    ADD COLUMN IF NOT EXISTS location_id BIGINT
        REFERENCES public.storage_locations(location_id);

-- Defensive clean-up so ADD CONSTRAINT cannot fail on legacy orphans (no-op on a fresh DB).
DELETE FROM public.inventory i
 WHERE NOT EXISTS (SELECT 1 FROM public.warehouses w WHERE w.warehouse_id = i.warehouse_id);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_inventory_warehouse') THEN
        ALTER TABLE public.inventory
            ADD CONSTRAINT fk_inventory_warehouse
            FOREIGN KEY (warehouse_id) REFERENCES public.warehouses(warehouse_id) ON DELETE CASCADE;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_inventory_batch ON public.inventory(batch_id);
CREATE INDEX IF NOT EXISTS idx_inventory_wh    ON public.inventory(warehouse_id);

-- Single source of truth for the running balance. BEFORE INSERT enforces the
-- floor without re-reading rows the current statement has not yet committed.
CREATE OR REPLACE FUNCTION public.check_inventory_floor() RETURNS TRIGGER
LANGUAGE plpgsql AS $fn$
BEGIN
    IF NEW.quantity_on_hand < 0 THEN
        RAISE EXCEPTION
            'inventory floor violated: batch % would go to % in warehouse %',
            NEW.batch_id, NEW.quantity_on_hand, NEW.warehouse_id
            USING HINT = 'INSERT an ''issue'' stock_movement only after enough receipts exist.';
    END IF;
    RETURN NEW;
END;
$fn$;

DROP TRIGGER IF EXISTS trg_inventory_floor ON public.inventory;
CREATE TRIGGER trg_inventory_floor
    BEFORE INSERT OR UPDATE OF quantity_on_hand ON public.inventory
    FOR EACH ROW EXECUTE FUNCTION public.check_inventory_floor();

-- Direct writes to inventory are forbidden: balances derive from movements only.
CREATE OR REPLACE FUNCTION public.forbid_direct_inventory_write() RETURNS TRIGGER
LANGUAGE plpgsql AS $fn$
BEGIN
    IF pg_trigger_depth() = 0 THEN
        RAISE EXCEPTION 'public.inventory is trigger-maintained; write to public.stock_movements instead';
    END IF;
    RETURN NEW;
END;
$fn$;

DROP TRIGGER IF EXISTS trg_inventory_guard ON public.inventory;
CREATE TRIGGER trg_inventory_guard
    BEFORE UPDATE OR DELETE ON public.inventory
    FOR EACH ROW EXECUTE FUNCTION public.forbid_direct_inventory_write();

-- The movement applier: AFTER INSERT adjusts both sides atomically.
CREATE OR REPLACE FUNCTION public.apply_stock_movement() RETURNS TRIGGER
LANGUAGE plpgsql AS $fn$
DECLARE
    v_missing BOOLEAN;
BEGIN
    IF NEW.from_warehouse_id IS NOT NULL THEN
        UPDATE public.inventory
           SET quantity_on_hand = quantity_on_hand - NEW.quantity,
               updated_at       = CURRENT_TIMESTAMP
         WHERE warehouse_id = NEW.from_warehouse_id
           AND batch_id     = NEW.batch_id;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'No stock row for batch % in warehouse %',
                NEW.batch_id, NEW.from_warehouse_id
                USING HINT = 'Receive the batch first (movement_type = ''receipt'').';
        END IF;

        -- Floor check that sees this transaction's own prior decrements.
        SELECT (quantity_on_hand < 0) INTO v_missing
          FROM public.inventory
         WHERE warehouse_id = NEW.from_warehouse_id AND batch_id = NEW.batch_id;
        IF v_missing THEN
            RAISE EXCEPTION 'Issue of % units exceeds stock of batch % in warehouse %',
                NEW.quantity, NEW.batch_id, NEW.from_warehouse_id;
        END IF;
    END IF;

    IF NEW.to_warehouse_id IS NOT NULL THEN
        INSERT INTO public.inventory (warehouse_id, batch_id, quantity_on_hand, location_id)
        VALUES (NEW.to_warehouse_id, NEW.batch_id, NEW.quantity, NEW.to_location_id)
        ON CONFLICT (warehouse_id, batch_id) DO UPDATE
           SET quantity_on_hand = public.inventory.quantity_on_hand + EXCLUDED.quantity_on_hand,
               updated_at       = CURRENT_TIMESTAMP,
               location_id      = COALESCE(EXCLUDED.location_id, public.inventory.location_id);
    END IF;

    RETURN NEW;
END;
$fn$;

DROP TRIGGER IF EXISTS trg_apply_stock_movement ON public.stock_movements;
CREATE TRIGGER trg_apply_stock_movement
    AFTER INSERT ON public.stock_movements
    FOR EACH ROW EXECUTE FUNCTION public.apply_stock_movement();

-- ---------------------------------------------------------------------------
-- 4) FEFO picker — First-Expired-First-Out allocation list
--    Returns candidate batches ordered by expiry; qty is what is on hand.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.fefo_batches(
    p_warehouse_id BIGINT,
    p_medicine_id  BIGINT,
    p_min_days     INTEGER DEFAULT 0
)
RETURNS TABLE (
    batch_id     BIGINT,
    batch_number VARCHAR(80),
    expiry_date  DATE,
    qty          INTEGER,
    purchase_price NUMERIC(12,2)
)
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $fn$
    SELECT b.batch_id,
           b.batch_number,
           b.expiry_date,
           i.quantity_on_hand::INTEGER,
           b.purchase_price
      FROM public.inventory i
      JOIN public.medicine_batches b USING (batch_id)
     WHERE i.warehouse_id   = p_warehouse_id
       AND b.medicine_id    = p_medicine_id
       AND i.quantity_on_hand > 0
       AND b.expiry_date > CURRENT_DATE + p_min_days      -- skip near-expiry stock
     ORDER BY b.expiry_date ASC, b.received_date ASC, b.batch_id ASC;
$fn$;

COMMENT ON FUNCTION public.fefo_batches(BIGINT, BIGINT, INTEGER) IS
    'FEFO pick list for (warehouse, medicine): earliest expiry first, positive on-hand only.';

COMMIT;

-- ===========================================================================
-- CONCURRENCY WARNINGS (read before scaling writes)
-- ===========================================================================
-- A) LOST-UPDATE / DEADLOCK RISK on public.inventory (warehouse_id, batch_id):
--    apply_stock_movement() runs `UPDATE ... quantity = quantity - n` (read-modify-write).
--    Two concurrent issues for the SAME (warehouse,batch) serialise on the row lock —
--    correct, but throughput collapses and hot batches can deadlock when a transfer
--    touches rows in opposite order across two sessions.
--    MITIGATION: keep each movement in ONE short transaction, and lock inventory rows
--    in deterministic (warehouse_id, batch_id) order, e.g.
--        SELECT 1 FROM inventory WHERE (warehouse_id,batch_id) IN (...)
--          ORDER BY warehouse_id, batch_id FOR UPDATE;
--    or funnel all writes through a single queue/worker.
-- B) THE CHECK (quantity_on_hand >= 0) CONSTRAINT BREAKS UNDER CONCURRENT ISSUES:
--    It is evaluated per-row at statement level, so it aborts one of the racing
--    transactions with "new row violates check constraint" rather than blocking it.
--    Combined with the trigger's in-transaction guard above, overselling is prevented,
--    but clients MUST be prepared to retry on CheckViolation / Serialization errors.
-- C) UNIQUE (warehouse_id, location_code) and UNIQUE (medicine_id, batch_number):
--    plain b-tree uniques reject only exact duplicates concurrently — safe — but they
--    do NOT deduplicate case-insensitive codes ('A-1' vs 'a-1'); add a functional index
--    on lower(location_code) if branch staff enter codes manually.
-- D) IDENTITY sequences (GENERATED ALWAYS AS IDENTITY) are non-transactional: a rolled
--    back movement leaves gaps in movement_id. Harmless for an audit trail; do not treat
--    movement_id as gap-free.
-- E) The append-only guard (trg_inventory_guard) uses pg_trigger_depth(), so a future
--    second trigger on inventory could bypass it; prefer REVOKE INSERT/UPDATE/DELETE
--    FROM inventory FROM PUBLIC and grant only SELECT to read-only roles.
