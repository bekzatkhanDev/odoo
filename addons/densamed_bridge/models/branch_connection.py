# -*- coding: utf-8 -*-
"""Branch/role/employee extraction queries + the branch-company mapper.

Everything read here is a SELECT on the *densamed* database (read-only session,
enforced in densamed_connection.py).  The branch mapper lives in this model so
that every other mapper can resolve `branch_id -> res.company` through one
shared helper: _branch_company_map().
"""
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class DensamedBranchConnection(models.AbstractModel):
    _inherit = 'densamed.connection'

    # ------------------------------------------------------------------
    # Source queries (READ-ONLY) — new for the Branch feature
    # ------------------------------------------------------------------
    SQL_BRANCHES = """
        SELECT b.branch_id,
               b.branch_code,
               b.branch_name,
               b.city,
               b.address,
               b.phone,
               b.is_active
          FROM public.branches b
      ORDER BY b.branch_id
    """

    SQL_ROLES = """
        SELECT r.role_id,
               r.role_name,
               r.description
          FROM public.roles r
      ORDER BY r.role_id
    """

    SQL_EMPLOYEES = """
        SELECT e.employee_id,
               e.branch_id,
               e.role_id,
               e.first_name,
               e.last_name,
               e.email,
               e.phone,
               e.hire_date,
               e.is_active,
               r.role_name
          FROM public.employees e
     LEFT JOIN public.roles r USING (role_id)
      ORDER BY e.employee_id
    """

    @api.model
    def get_branches(self):
        return self.fetchall(self.SQL_BRANCHES)

    @api.model
    def get_roles(self):
        return self.fetchall(self.SQL_ROLES)

    @api.model
    def get_employees(self):
        return self.fetchall(self.SQL_EMPLOYEES)

    # ------------------------------------------------------------------
    # Shared resolution helper: densamed branch_id -> res.company recordset.
    # Every downstream mapper (warehouses, locations, lots, employees) must
    # go through this; nothing may invent its own join.
    # ------------------------------------------------------------------
    @api.model
    def _branch_company_map(self, include_inactive=True):
        Company = self.env['res.company'].sudo().with_context(active_test=False)
        domain = [('x_densamed_branch_id', '!=', False)]
        if not include_inactive:
            domain.append(('active', '=', True))
        return {c.x_densamed_branch_id: c for c in Company.search(domain)}
