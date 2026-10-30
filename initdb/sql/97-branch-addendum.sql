-- =============================================================================
-- 97-branch-addendum.sql — DensaMed Branch feature, DensaMed side (phase 2).
-- Runs in the `densamed` database with ON_ERROR_STOP=1. No extensions used.
-- =============================================================================

SET client_encoding = 'UTF8';

-- -----------------------------------------------------------------------------
-- role_group_map: FK target for the role -> Odoo-group lookup consumed by the
-- densamed_bridge.role_group_map model. Kept on the DensaMed side so branch
-- managers can propose mappings where they already work; auto_assign is
-- deliberately IGNORED by the bridge (groups are applied only through the
-- manual "Apply branch roles" wizard — see models/role_group_map.py for why).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.role_group_map (
    role_id      BIGINT PRIMARY KEY REFERENCES public.roles(role_id) ON DELETE CASCADE,
    odoo_group   VARCHAR(120) NOT NULL,   -- e.g. 'stock.group_stock_user'
    auto_assign  BOOLEAN NOT NULL DEFAULT FALSE
);

-- Sensible defaults mirroring the module CSV seed (job != security group).
INSERT INTO public.role_group_map (role_id, odoo_group, auto_assign) VALUES
    (1, 'stock.group_stock_user',                 FALSE),  -- Pharmacist
    (2, 'stock.group_stock_user',                 FALSE),  -- Cashier
    (3, 'stock.group_stock_manager',              FALSE)   -- Manager (part 1)
ON CONFLICT (role_id) DO NOTHING;
-- NOTE: one row per (role, group) pair would need a composite PK; the spec's
-- single-column PK means a role maps to exactly ONE suggested group here. The
-- richer N:N mapping lives Odoo-side in densamed_bridge.role_group_map
-- (Manager -> stock.group_stock_manager + sales_team.group_sale_manager).

COMMENT ON COLUMN public.role_group_map.auto_assign IS
    'Read but NEVER acted upon by the sync: privilege changes must be a human decision.';
