-- DensaMed pharmacy chain database
-- PostgreSQL schema for an educational ERP project.
-- Run this script while connected to the densamed_db database.
-- This script creates tables only; sample data and business logic can be added later.

BEGIN;

CREATE TABLE IF NOT EXISTS public.branches (
    branch_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    branch_code VARCHAR(20) NOT NULL UNIQUE,
    branch_name VARCHAR(120) NOT NULL,
    city VARCHAR(80) NOT NULL,
    address TEXT NOT NULL,
    phone VARCHAR(30),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS public.roles (
    role_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    role_name VARCHAR(80) NOT NULL UNIQUE,
    description TEXT
);

CREATE TABLE IF NOT EXISTS public.employees (
    employee_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    branch_id BIGINT REFERENCES public.branches(branch_id) ON DELETE SET NULL,
    role_id BIGINT NOT NULL REFERENCES public.roles(role_id),
    first_name VARCHAR(80) NOT NULL,
    last_name VARCHAR(80) NOT NULL,
    email VARCHAR(160) UNIQUE,
    phone VARCHAR(30),
    hire_date DATE NOT NULL DEFAULT CURRENT_DATE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS public.suppliers (
    supplier_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    supplier_name VARCHAR(160) NOT NULL,
    business_id VARCHAR(20) UNIQUE,
    phone VARCHAR(30),
    email VARCHAR(160),
    address TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS public.manufacturers (
    manufacturer_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    manufacturer_name VARCHAR(160) NOT NULL UNIQUE,
    country VARCHAR(80)
);

CREATE TABLE IF NOT EXISTS public.categories (
    category_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    category_name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT
);

CREATE TABLE IF NOT EXISTS public.medicines (
    medicine_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    barcode VARCHAR(80) UNIQUE,
    trade_name VARCHAR(160) NOT NULL,
    generic_name VARCHAR(160),
    category_id BIGINT REFERENCES public.categories(category_id) ON DELETE SET NULL,
    manufacturer_id BIGINT REFERENCES public.manufacturers(manufacturer_id) ON DELETE SET NULL,
    dosage_form VARCHAR(80),
    strength VARCHAR(50),
    unit_of_measure VARCHAR(30) NOT NULL DEFAULT 'упаковка',
    retail_price NUMERIC(12,2) NOT NULL CHECK (retail_price >= 0),
    requires_prescription BOOLEAN NOT NULL DEFAULT FALSE,
    min_stock INTEGER NOT NULL DEFAULT 0 CHECK (min_stock >= 0),
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS public.warehouses (
    warehouse_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    branch_id BIGINT NOT NULL REFERENCES public.branches(branch_id),
    warehouse_name VARCHAR(120) NOT NULL,
    location_description TEXT,
    UNIQUE (branch_id, warehouse_name)
);

CREATE TABLE IF NOT EXISTS public.purchase_orders (
    purchase_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    supplier_id BIGINT NOT NULL REFERENCES public.suppliers(supplier_id),
    branch_id BIGINT NOT NULL REFERENCES public.branches(branch_id),
    employee_id BIGINT NOT NULL REFERENCES public.employees(employee_id),
    order_date DATE NOT NULL DEFAULT CURRENT_DATE,
    expected_date DATE,
    status VARCHAR(24) NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'ordered', 'partially_received', 'received', 'cancelled')),
    notes TEXT,
    CHECK (expected_date IS NULL OR expected_date >= order_date)
);

CREATE TABLE IF NOT EXISTS public.purchase_items (
    purchase_item_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    purchase_id BIGINT NOT NULL REFERENCES public.purchase_orders(purchase_id) ON DELETE CASCADE,
    medicine_id BIGINT NOT NULL REFERENCES public.medicines(medicine_id),
    quantity_ordered INTEGER NOT NULL CHECK (quantity_ordered > 0),
    quantity_received INTEGER NOT NULL DEFAULT 0
        CHECK (quantity_received >= 0 AND quantity_received <= quantity_ordered),
    unit_cost NUMERIC(12,2) NOT NULL CHECK (unit_cost >= 0)
);

CREATE TABLE IF NOT EXISTS public.medicine_batches (
    batch_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    medicine_id BIGINT NOT NULL REFERENCES public.medicines(medicine_id),
    purchase_item_id BIGINT REFERENCES public.purchase_items(purchase_item_id) ON DELETE SET NULL,
    batch_number VARCHAR(80) NOT NULL,
    manufacture_date DATE,
    expiry_date DATE NOT NULL,
    purchase_price NUMERIC(12,2) NOT NULL CHECK (purchase_price >= 0),
    received_date DATE NOT NULL DEFAULT CURRENT_DATE,
    UNIQUE (medicine_id, batch_number),
    CHECK (manufacture_date IS NULL OR expiry_date > manufacture_date)
);

CREATE TABLE IF NOT EXISTS public.inventory (
    warehouse_id BIGINT NOT NULL REFERENCES public.warehouses(warehouse_id),
    batch_id BIGINT NOT NULL REFERENCES public.medicine_batches(batch_id),
    quantity_on_hand INTEGER NOT NULL DEFAULT 0 CHECK (quantity_on_hand >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (warehouse_id, batch_id)
);

CREATE TABLE IF NOT EXISTS public.customers (
    customer_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_name VARCHAR(160) NOT NULL,
    phone VARCHAR(30),
    email VARCHAR(160),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS public.sales (
    sale_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    branch_id BIGINT NOT NULL REFERENCES public.branches(branch_id),
    employee_id BIGINT NOT NULL REFERENCES public.employees(employee_id),
    customer_id BIGINT REFERENCES public.customers(customer_id) ON DELETE SET NULL,
    sale_date TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(20) NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'completed', 'cancelled', 'returned')),
    total_amount NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (total_amount >= 0)
);

CREATE TABLE IF NOT EXISTS public.sale_items (
    sale_item_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sale_id BIGINT NOT NULL REFERENCES public.sales(sale_id) ON DELETE CASCADE,
    batch_id BIGINT NOT NULL REFERENCES public.medicine_batches(batch_id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(12,2) NOT NULL CHECK (unit_price >= 0),
    discount_amount NUMERIC(12,2) NOT NULL DEFAULT 0
        CHECK (discount_amount >= 0 AND discount_amount <= quantity * unit_price)
);

CREATE TABLE IF NOT EXISTS public.payments (
    payment_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sale_id BIGINT REFERENCES public.sales(sale_id) ON DELETE CASCADE,
    purchase_id BIGINT REFERENCES public.purchase_orders(purchase_id) ON DELETE CASCADE,
    payment_date TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    amount NUMERIC(12,2) NOT NULL CHECK (amount > 0),
    payment_method VARCHAR(24) NOT NULL
        CHECK (payment_method IN ('cash', 'card', 'bank_transfer', 'other')),
    payment_status VARCHAR(20) NOT NULL DEFAULT 'completed'
        CHECK (payment_status IN ('pending', 'completed', 'cancelled', 'refunded')),
    CHECK (
        (sale_id IS NOT NULL AND purchase_id IS NULL)
        OR
        (sale_id IS NULL AND purchase_id IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS public.demand_forecasts (
    forecast_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    branch_id BIGINT NOT NULL REFERENCES public.branches(branch_id),
    medicine_id BIGINT NOT NULL REFERENCES public.medicines(medicine_id),
    forecast_date DATE NOT NULL,
    predicted_quantity NUMERIC(12,2) NOT NULL CHECK (predicted_quantity >= 0),
    model_version VARCHAR(50) NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (branch_id, medicine_id, forecast_date, model_version)
);

CREATE INDEX IF NOT EXISTS idx_purchase_orders_order_date
    ON public.purchase_orders(order_date);

CREATE INDEX IF NOT EXISTS idx_sales_branch_date
    ON public.sales(branch_id, sale_date);

CREATE INDEX IF NOT EXISTS idx_medicine_batches_expiry
    ON public.medicine_batches(expiry_date);

CREATE INDEX IF NOT EXISTS idx_inventory_batch
    ON public.inventory(batch_id);

CREATE INDEX IF NOT EXISTS idx_demand_forecasts_date
    ON public.demand_forecasts(forecast_date);
-- Location hierarchy: zone → aisle → shelf → bin
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

-- Immutable audit trail: every stock change is a row here
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
    reference_type    VARCHAR(24),
    reference_id      BIGINT,
    performed_by      BIGINT REFERENCES public.employees(employee_id),
    performed_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (from_warehouse_id IS NOT NULL OR to_warehouse_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_movements_batch
    ON public.stock_movements(batch_id, performed_at);

-- Apply every movement to the inventory balance atomically
CREATE OR REPLACE FUNCTION public.apply_stock_movement() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.from_warehouse_id IS NOT NULL THEN
        UPDATE public.inventory
           SET quantity_on_hand = quantity_on_hand - NEW.quantity,
               updated_at = CURRENT_TIMESTAMP
         WHERE warehouse_id = NEW.from_warehouse_id AND batch_id = NEW.batch_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'No stock row for batch % in warehouse %',
                NEW.batch_id, NEW.from_warehouse_id;
        END IF;
    END IF;

    IF NEW.to_warehouse_id IS NOT NULL THEN
        INSERT INTO public.inventory (warehouse_id, batch_id, quantity_on_hand)
        VALUES (NEW.to_warehouse_id, NEW.batch_id, NEW.quantity)
        ON CONFLICT (warehouse_id, batch_id) DO UPDATE
           SET quantity_on_hand = public.inventory.quantity_on_hand + EXCLUDED.quantity_on_hand,
               updated_at = CURRENT_TIMESTAMP;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_apply_stock_movement
    AFTER INSERT ON public.stock_movements
    FOR EACH ROW EXECUTE FUNCTION public.apply_stock_movement();

-- FEFO pick list (First-Expired, First-Out)
CREATE OR REPLACE FUNCTION public.fefo_batches(p_warehouse_id BIGINT, p_medicine_id BIGINT)
RETURNS TABLE (batch_id BIGINT, batch_number VARCHAR, expiry_date DATE, qty INTEGER)
AS $$
    SELECT b.batch_id, b.batch_number, b.expiry_date, i.quantity_on_hand
      FROM public.inventory i
      JOIN public.medicine_batches b USING (batch_id)
     WHERE i.warehouse_id = p_warehouse_id
       AND b.medicine_id  = p_medicine_id
       AND i.quantity_on_hand > 0
     ORDER BY b.expiry_date ASC, b.batch_id ASC;
$$ LANGUAGE sql STABLE;

COMMIT;
