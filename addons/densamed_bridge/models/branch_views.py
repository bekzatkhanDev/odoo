# -*- coding: utf-8 -*-
"""Deliverable 3 — branch_id plumbing on operational documents.

`branch_id` is a *related, stored* pointer to the DensaMed branch key carried
by the record's company. It is read-only everywhere: the company is the source
of truth (set by the sync or by standard Odoo multi-company flows), never this
field. Related-stored also makes it usable in group-bys and search filters
without extra SQL.
"""
from odoo import fields, models


class BranchMixin(models.AbstractModel):
    _name = 'densamed_bridge.branch_mixin'
    _description = 'DensaMed Branch (via company) mixin'

    # NOTE: company_id is NOT defined on this abstract mixin; related fields
    # referencing company_id are declared on the concrete models that inherit
    # company_id natively (purchase.order, sale.order, etc.).


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    # purchase.order already HAS company_id (native). We only expose the branch.
    branch_id = fields.Many2one(
        'res.company', string='Branch',
        related='company_id', store=False, readonly=True,
        help='The branch IS the company (modelling decision, see res_company.py).')
    x_densamed_branch_id = fields.Integer(
        string='DensaMed Branch ID', related='company_id.x_densamed_branch_id',
        store=True, readonly=True, index=True)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    branch_id = fields.Many2one(
        'res.company', string='Branch',
        related='company_id', store=False, readonly=True)
    x_densamed_branch_id = fields.Integer(
        string='DensaMed Branch ID', related='company_id.x_densamed_branch_id',
        store=True, readonly=True, index=True)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    branch_id = fields.Many2one(
        'res.company', string='Branch',
        related='company_id', store=False, readonly=True)
    x_densamed_branch_id = fields.Integer(
        string='DensaMed Branch ID', related='company_id.x_densamed_branch_id',
        store=True, readonly=True, index=True)


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    # READ-ONLY exposure. The bridge NEVER writes stock.quant (hard rule);
    # company_id below is native on stock.quant since Odoo 16 — we rely on it,
    # we do not redefine it.
    branch_id = fields.Many2one(
        'res.company', string='Branch',
        related='company_id', store=False, readonly=True)
    x_densamed_branch_id = fields.Integer(
        string='DensaMed Branch ID', related='company_id.x_densamed_branch_id',
        store=True, readonly=True, index=True)
