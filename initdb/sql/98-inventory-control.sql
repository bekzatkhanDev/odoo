-- =============================================================================
-- 98-inventory-control.sql — DensaMed inventory control schema (initdb phase 2)
-- Runs in the `densamed` database as ${POSTGRES_USER} with ON_ERROR_STOP=1.
-- No CREATE EXTENSION required (no gen_random_uuid() used below).
-- =============================================================================

SET client_encoding = 'UTF8';
SET statement_timeout = 0;

CREATE SCHEMA IF NOT EXISTS densamed_fdw;

-- -----------------------------------------------------------------------------
-- storage_locations: physical shelf/bin hierarchy inside a branch warehouse.
-- location_type: zone | aisle | shelf | bin ; usage mirrors Odoo semantics.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS densamed_fdw.storage_locations (
    location_id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    warehouse_id         BIGINT        NOT NULL,
    parent_id            BIGINT        NULL,
    location_code        VARCHAR(64)   NOT NULL,
    location_name        VARCHAR(120)  NOT NULL,
    location_description TEXT          NULL,
    location_type        VARCHAR(16)   NOT NULL DEFAULT 'bin',
    usage                VARCHAR(16)   NOT NULL DEFAULT 'internal',
    is_active            BOOLEAN       NOT NULL DEFAULT TRUE,
    CONSTRAINT fk_storage_location_warehouse FOREIGN KEY (warehouse_id)
        REFERENCES public.warehouses(warehouse_id) ON DELETE CASCADE,
    -- self-reference guarded by CHECK so root rows may keep parent_id = 0
    CONSTRAINT ck_storage_location_no_self_parent CHECK (parent_id IS NULL OR parent_id <> location_id),
    CONSTRAINT fk_storage_location_parent FOREIGN KEY (parent_id)
        REFERENCES densamed_fdw.storage_locations(location_id) ON DELETE SET NULL,
    CONSTRAINT ck_location_type CHECK (location_type IN ('zone','aisle','shelf','bin')),
    CONSTRAINT ck_usage         CHECK (usage IN ('internal','transit','view','customer','supplier','inventory','production')),
    CONSTRAINT uq_storage_location_code UNIQUE (warehouse_id, location_code)
);
CREATE INDEX IF NOT EXISTS ix_storage_locations_wh     ON densamed_fdw.storage_locations (warehouse_id);
CREATE INDEX IF NOT EXISTS ix_storage_locations_parent ON densamed_fdw.storage_locations (parent_id);

-- -----------------------------------------------------------------------------
-- stock_movements: immutable event log (append-only ledger of receipts/issues).
-- movement_type: receipt | issue | transfer | adjustment | return
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS densamed_fdw.stock_movements (
    movement_id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    medicine_id    BIGINT       NOT NULL,
    batch_id       BIGINT       NOT NULL,
    warehouse_id   BIGINT       NOT NULL,
    location_id    BIGINT       NULL,
    movement_type  VARCHAR(16)  NOT NULL,
    quantity       NUMERIC(14,3) NOT NULL CHECK (quantity > 0),
    reference      VARCHAR(64)  NULL,
    moved_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    created_by     VARCHAR(64)  NOT NULL DEFAULT CURRENT_USER,
    CONSTRAINT fk_sm_medicine   FOREIGN KEY (medicine_id)  REFERENCES public.medicines(medicine_id),
    CONSTRAINT fk_sm_batch      FOREIGN KEY (batch_id)     REFERENCES public.medicine_batches(batch_id),
    CONSTRAINT fk_sm_warehouse  FOREIGN KEY (warehouse_id) REFERENCES public.warehouses(warehouse_id),
    CONSTRAINT fk_sm_location   FOREIGN KEY (location_id)  REFERENCES densamed_fdw.storage_locations(location_id),
    CONSTRAINT ck_sm_type CHECK (movement_type IN ('receipt','issue','transfer','adjustment','return'))
);
CREATE INDEX IF NOT EXISTS ix_sm_batch ON densamed_fdw.stock_movements (batch_id, moved_at DESC);
CREATE INDEX IF NOT EXISTS ix_sm_wh    ON densamed_fdw.stock_movements (warehouse_id, moved_at DESC);

-- -----------------------------------------------------------------------------
-- inventory: current on-hand per (warehouse, batch). ONE ROW PER PAIR — this
-- is the table whose UNIQUE constraint races under concurrent receipts; see
-- "Concurrency notes" at the bottom of this file for the full analysis.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS densamed_fdw.inventory (
    inventory_id      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    warehouse_id      BIGINT        NOT NULL,
    batch_id          BIGINT        NOT NULL,
    quantity_on_hand  NUMERIC(14,3) NOT NULL DEFAULT 0,
    last_movement_id  BIGINT        NULL,
    updated_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_inv_warehouse FOREIGN KEY (warehouse_id) REFERENCES public.warehouses(warehouse_id) ON DELETE CASCADE,
    CONSTRAINT fk_inv_batch     FOREIGN KEY (batch_id)     REFERENCES public.medicine_batches(batch_id) ON DELETE CASCADE,
    CONSTRAINT uq_inventory_wh_batch UNIQUE (warehouse_id, batch_id),
    CONSTRAINT ck_inv_nonneg CHECK (quantity_on_hand >= 0)
);

-- -----------------------------------------------------------------------------
-- apply_stock_movement(): AFTER INSERT trigger keeping inventory in sync with
-- the stock_movements ledger. FEFO-aware issue deduction lives in fefo_batches().
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION densamed_fdw.apply_stock_movement() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_delta NUMERIC(14,3);
BEGIN
    -- Signed delta from movement type
    v_delta := CASE NEW.movement_type
                   WHEN 'receipt'    THEN  NEW.quantity
                   WHEN 'return'     THEN  NEW.quantity
                   WHEN 'adjustment' THEN  NEW.quantity
                   WHEN 'issue'      THEN -NEW.quantity
                   WHEN 'transfer'   THEN  0      -- handled by paired rows
               END;

    -- CONCURRENCY: advisory xact lock keyed on (warehouse_id, batch_id)
    -- serialises upserts for the SAME inventory slot without blocking other
    -- slots. ON CONFLICT alone does NOT prevent the lost-update race here:
    -- two simultaneous first-time receipts of the same pair both miss the row,
    -- one INSERT wins, the other raises UniqueViolation (ON CONFLICT only
    -- covers read-modify-write once the row exists). The lock makes the whole
    -- read-upsert-notify sequence atomic per slot. See "Concurrency notes".
    PERFORM pg_advisory_xact_lock(hashtext(NEW.warehouse_id::text || ':' || NEW.batch_id::text));

    INSERT INTO densamed_fdw.inventory AS inv
           (warehouse_id, batch_id, quantity_on_hand, last_movement_id, updated_at)
    VALUES (NEW.warehouse_id, NEW.batch_id, GREATEST(v_delta, 0), NEW.movement_id, NOW())
    ON CONFLICT (warehouse_id, batch_id) DO UPDATE
       SET quantity_on_hand = inv.quantity_on_hand + EXCLUDED.quantity_on_hand
                                      - CASE WHEN EXCLUDED.quantity_on_hand = 0 AND inv.quantity_on_hand < 0 THEN 0 ELSE 0 END,
           last_movement_id = EXCLUDED.last_movement_id,
           updated_at       = NOW();

    -- Issues/adjustments can drive the slot negative before the CHECK fires;
    -- clamp via explicit guard so the ledger stays authoritative.
    UPDATE densamed_fdw.inventory
       SET quantity_on_hand = GREATEST(quantity_on_hand, 0)
     WHERE warehouse_id = NEW.warehouse_id AND batch_id = NEW.batch_id;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_stock_movements_apply ON densamed_fdw.stock_movements;
CREATE TRIGGER trg_stock_movements_apply
    AFTER INSERT ON densamed_fdw.stock_movements
    FOR EACH ROW EXECUTE FUNCTION densamed_fdw.apply_stock_movement();

-- -----------------------------------------------------------------------------
-- fefo_batches(): FIFO-by-expiry picker — returns batches of a medicine in a
-- warehouse ordered earliest-expiry-first with available quantities.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION densamed_fdw.fefo_batches(
    p_medicine_id  BIGINT,
    p_warehouse_id BIGINT,
    p_quantity     NUMERIC DEFAULT NULL
) RETURNS TABLE (
    batch_id        BIGINT,
    batch_number    VARCHAR,
    expiry_date     DATE,
    quantity_on_hand NUMERIC,
    allocated        NUMERIC
) LANGUAGE sql STABLE AS $$
    WITH candidates AS (
        SELECT b.batch_id,
               b.batch_number,
               m.expiry_date,
               COALESCE(i.quantity_on_hand, 0) AS quantity_on_hand
          FROM public.medicine_batches b
          JOIN public.medicines m USING (medicine_id)
     LEFT JOIN densamed_fdw.inventory i
            ON i.batch_id = b.batch_id AND i.warehouse_id = p_warehouse_id
         WHERE m.medicine_id = p_medicine_id
           AND COALESCE(i.quantity_on_hand, 0) > 0
           AND m.expiry_date > CURRENT_DATE          -- expired stock never FEFO-picked
      ORDER BY m.expiry_date ASC, b.batch_id ASC      -- FEFO tie-break stable
    )
    SELECT c.batch_id,
           c.batch_number,
           c.expiry_date,
           c.quantity_on_hand,
           CASE
             WHEN p_quantity IS NULL THEN 0
             WHEN running.running_qty <= p_quantity THEN c.quantity_on_hand
             WHEN running.running_qty - c.quantity_on_hand < p_quantity
                  THEN p_quantity - (running.running_qty - c.quantity_on_hand)
             ELSE 0
           END AS allocated
      FROM (SELECT *, SUM(quantity_on_hand) OVER (ORDER BY expiry_date, batch_id) AS running_qty
              FROM candidates) c
     WHERE p_quantity IS NULL
        OR c.running_qty - c.quantity_on_hand < p_quantity;
$$;

-- Seed storage locations consistent with existing warehouses (branch 1 & 2).
INSERT INTO densamed_fdw.storage_locations
       (warehouse_id, parent_id, location_code, location_name, location_type, usage)
VALUES
       (1, NULL, 'RCV',  'Receiving Zone',        'zone', 'view'),
       (1, NULL, 'STR',  'Storage Aisle',         'aisle','view'),
       (1, NULL, 'BIN-A1','Cold Chain Bin A1',    'bin',  'internal')
ON CONFLICT (warehouse_id, location_code) DO NOTHING;

-- =============================================================================
-- Concurrency notes
-- =============================================================================
-- 1. UNIQUE (warehouse_id, batch_id) on densamed_fdw.inventory combined with
--    apply_stock_movement(): two simultaneous FIRST receipts of the same batch
--    into the same warehouse race on INSERT ... ON CONFLICT DO UPDATE — both
--    transactions miss the row, one INSERT wins, the other gets
--    UniqueViolation (the arbiter cannot help when the conflicting row did not
--    exist at planning time and both snapshots agree it is absent). Even after
--    the row exists, plain "read-modify-write" would lose updates. VERDICT:
--    ON CONFLICT alone is NOT sufficient. We therefore take
--    pg_advisory_xact_lock(hashtext('wh:batch')) at the top of the trigger
--    (already included above): serialises per-slot writers, keeps row-level
--    concurrency across different slots, transaction-scoped (auto-release),
--    deadlock-free because every writer takes exactly ONE lock and lock order
--    across multiple movements follows the single-statement path.
--    SERIALIZABLE isolation would also work but aborts far more innocent
--    transactions (SSI false positives) and requires retry logic everywhere —
--    advisory lock is the cheaper correct choice here.
-- 2. medicine_batches (medicine_id, batch_number) UNIQUE: a cron batch-sync
--    racing a manual entry on the same pair raises UniqueViolation. The Odoo
--    side must use the match-on-(densamed_model, densamed_id) upsert inside a
--    savepoint and, on UniqueViolation, ROLLBACK TO SAVEPOINT and re-run the
--    mapper once (second pass finds the now-existing row and converts INSERT
--    to UPDATE). Implemented in models/sync_log.py run_job() retry loop.
-- 3. res_company.x_densamed_branch_id unique index: two concurrent copies of
--    the branch cron could both try to create the same company. Defence layers:
--    (a) ir.cron claims its job row atomically (`FOR NO KEY UPDATE SKIP
--    LOCKED`) so one job never runs twice in the same or across workers of one
--    deployment — normally SUFFICIENT; (b) if crons are replicated externally
--    (k8s CronJob hitting odoo shell), wrap the upsert with
--    pg_advisory_xact_lock(<fixed key 7500001>) via
--    densamed.sync._advisory_lock() — provided and documented, off by default.
-- =============================================================================
