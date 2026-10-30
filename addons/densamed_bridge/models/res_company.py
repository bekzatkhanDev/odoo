# -*- coding: utf-8 -*-
"""res.company  <->  densamed.branches  (Deliverable 1).

Modelling choice — stated explicitly, because it is the keystone of the whole
branch feature:

A DensaMed `branches` row is modelled as an Odoo **res.company**, NOT as a
stock.warehouse and NOT as a plan.analytic_account.  A branch in the pharmacy
chain is an operating entity with its own employees, purchases, sales, stock
and P&L; that is exactly what a company is in Odoo.  Choosing companies buys,
out of the box and for free in Community 17:
  * record rules (`company_id in company_ids`) on warehouse / location /
    picking / move / quant / purchase.order / sale.order,
  * the branch switcher in the top bar (base.group_multi_company),
  * per-company stock valuation and multi-company consolidated reporting,
  * correct accounting dimensions later without any custom analytic axis.
Analytic accounts were rejected deliberately: they are a *reporting tag*, not
an access-control boundary — they cannot enforce visibility, cannot scope
pickings, and would force us to re-implement half of Odoo's multi-company
machinery by hand.

One company may still contain several warehouses (densamed.warehouses rows),
which matches the operational schema: warehouses.branch_id -> branches.
"""
from odoo import api, fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    # Join key for EVERY downstream sync. Named x_densamed_branch_id per spec.
    x_densamed_branch_id = fields.Integer(
        string='DensaMed Branch ID', copy=False, index=True, tracking=True,
        help='Primary key of the row in densamed.public.branches this company '
             'mirrors. Never reuse: every other mapper resolves branch_id '
             'through this column.')
    x_densamed_ref = fields.Char(
        string='Branch Code', related='partner_id.ref', store=True, index=True,
        readonly=True,
        help='branch_code mirrored from DensaMed. res.company has no native '
             '"ref" column in Community 17 (verified against '
             'odoo/addons/base/models/res_company.py); the canonical place for '
             'a company reference code is its partner\'s `ref`, so we mirror '
             'it there and expose it through this related field. Uniqueness is '
             'enforced by partial SQL constraint below via x_densamed_branch_id '
             '(the true join key) plus a search-level guard in the sync.')
    _sql_constraints = [
        ('densamed_branch_uniq',
         'unique(x_densamed_branch_id)',
         'Two companies cannot map to the same DensaMed branch row.'),
    ]

    is_densamed_branch = fields.Boolean(
        string='Is DensaMed Branch', compute='_compute_is_densamed_branch',
        store=True)

    @api.depends('x_densamed_branch_id')
    def _compute_is_densamed_branch(self):
        for company in self:
            company.is_densamed_branch = bool(company.x_densamed_branch_id)

    # ------------------------------------------------------------------
    # HQ convenience: members of group_densamed_hq must be attached to every
    # branch company, otherwise the built-in company rules hide records from
    # the very people who are supposed to see all of them.
    # ------------------------------------------------------------------
    @api.model
    def _ensure_hq_membership(self):
        hq = self.env.ref('densamed_bridge.group_densamed_hq', raise_if_not_found=False)
        if not hq:
            return 0
        branch_companies = self.search([('x_densamed_branch_id', '!=', False)])
        added = 0
        for user in hq.users:
            missing = branch_companies - user.company_ids
            if missing:
                user.write({'company_ids': [(4, c.id) for c in missing]})
                added += len(missing)
        return added
