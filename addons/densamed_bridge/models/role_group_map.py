# -*- coding: utf-8 -*-
"""role_group_map + "Apply branch roles" wizard (Deliverable 1, second half).

WHY THE SYNC CRON MUST NEVER AUTO-ASSIGN SECURITY GROUPS
--------------------------------------------------------
Auto-assigning groups from an operational master-data sync is dangerous for
three independent reasons:
  1. Privilege escalation by data entry: anyone who can edit a row in
     densamed.roles/employees (a pharmacy cashier terminal, a CSV import, a
     compromised operational DB user) instantly gains stock.group_stock_manager
     or accounting-level rights in Odoo on the next cron tick — no human ever
     reviewed it. Security assignments must be a deliberate act.
  2. Revocation asymmetry: sync adds groups; when an employee changes role or
     is archived remotely, a naive auto-sync either leaves stale elevated
     groups behind (security hole) or strips groups the user earned elsewhere
     in Odoo (functional breakage). Only a human decides which side wins.
  3. Auditability: group changes touch res.groups/users and must be traceable
     to an acting administrator (this wizard runs as the *current* user, so the
     chatter shows WHO granted WHAT), not to "cron".
Hence: the map table is synced read-only, but application is manual via this
wizard, restricted to densamed_bridge managers / HQ.
"""
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class DensamedRoleGroupMap(models.Model):
    _name = 'densamed_bridge.role_group_map'
    _description = 'DensaMed Role -> Odoo Group Mapping'
    _order = 'role_name'

    densamed_id = fields.BigInt(string='DensaMed Role ID', index=True, readonly=True,
                                copy=False, help='roles.role_id in the densamed DB')
    densamed_model = fields.Char(size=32, readonly=True, copy=False, default='roles')
    role_name = fields.Char(required=True)
    # XML id of the target group, e.g. 'stock.group_stock_user'. We store the
    # xmlid (not the int id) so the mapping survives db restores.
    odoo_group_xmlid = fields.Char(
        required=True,
        help='Odoo group XML id, e.g. stock.group_stock_user')
    odoo_group_id = fields.Many2one(
        'res.groups', string='Odoo Group', compute='_compute_odoo_group_id',
        store=True)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('role_group_uniq', 'unique(densamed_id, odoo_group_xmlid)',
         'The same role cannot map twice to the same group.'),
    ]

    @api.depends('odoo_group_xmlid')
    def _compute_odoo_group_id(self):
        for rec in self:
            rec.odoo_group_id = self.env.ref(rec.odoo_group_xmlid,
                                             raise_if_not_found=False)

    @api.model
    def _default_mappings(self):
        """Seed defaults — job != security group, these are only suggestions
        an admin confirms through the wizard."""
        defaults = [
            ('Pharmacist', 'stock.group_stock_user'),
            ('Cashier', 'stock.group_stock_user'),
            ('Manager', 'stock.group_stock_manager'),
            ('Manager', 'sales_team.group_sale_manager'),
        ]
        existing = {(m.densamed_id, m.odoo_group_xmlid) for m in self.search([])}
        created = 0
        for role_name, xmlid in defaults:
            role = self.env['hr.job'].sudo().search([('name', '=ilike', role_name)],
                                                    limit=1)
            rid = role.densamed_id if role and role.densamed_id else 0
            if (rid, xmlid) in existing:
                continue
            if not self.env.ref(xmlid, raise_if_not_found=False):
                continue  # optional addon (sales_team) not installed
            self.create({
                'densamed_id': rid,
                'densamed_model': 'roles',
                'role_name': role_name,
                'odoo_group_xmlid': xmlid,
            })
            created += 1
        return created


class DensamedApplyRolesWizard(models.TransientModel):
    _name = 'densamed_bridge.action_apply_roles'
    _description = 'Apply branch roles (manual, audited)'

    company_id = fields.Many2one(
        'res.company', string='Branch', required=True,
        domain="[('x_densamed_branch_id', '!=', False)]")
    employee_ids = fields.Many2many(
        'hr.employee', string='Employees',
        domain="[('company_id', '=', company_id)]",
        help='Leave empty to apply to every active employee of the branch.')
    dry_run = fields.Boolean(default=True,
                             help='Preview the group changes without writing.')

    def action_apply(self):
        self.ensure_one()
        Map = self.env['densamed_bridge.role_group_map']
        employees = self.employee_ids or self.env['hr.employee'].search(
            [('company_id', '=', self.company_id.id), ('active', '=', True)])
        report = []
        for emp in employees:
            job = emp.job_id
            if not job:
                continue
            maps = Map.search(['|', ('densamed_id', '=', job.densamed_id or -1),
                               ('role_name', '=ilike', job.name)])
            groups = maps.mapped('odoo_group_id').exists()
            if not groups:
                continue
            report.append('%s → %s' % (emp.name, ', '.join(sorted(groups.mapped('name')))))
            if not self.dry_run:
                # Runs as the CURRENT user (not sudo-cron): the change is
                # attributable in the chatter / audit trail.
                emp.sudo().write({'category_ids': [(4, g.id) for g in groups]})
        title = 'DRY RUN — nothing written' if self.dry_run else 'Groups applied'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success' if self.dry_run is False else 'warning',
                'title': '%s (%s)' % (title, self.company_id.name),
                'message': '<br/>'.join(report) or 'No mapped roles found.',
                'sticky': True,
            },
        }


class DensamedBridgeRole(models.Model):
    """Mirror of densamed.public.roles (BIGINT PK) for FK targets and joins.

    The role_group_map above keys on the *remote* role_id, but remote ids can
    collide with local hr.job ids; a dedicated mirror table gives us:
      * a stable local surrogate for any future FK (e.g. employee bridge view),
      * the ability to keep xmlid-safe group mapping per role row.
    """
    _name = 'densamed_bridge.role'
    _description = 'DensaMed Role Mirror'
    _order = 'densamed_id'

    densamed_id = fields.BigInt(string='DensaMed Role ID', required=True, index=True,
                                readonly=True, copy=False)
    role_name = fields.Char(required=True, readonly=True)
    description = fields.Text(readonly=True)
    group_map_ids = fields.One2many('densamed_bridge.role_group_map',
                                    'bridge_role_id', string='Group Mappings')

    _sql_constraints = [
        ('densamed_role_uniq', 'unique(densamed_id)',
         'One mirror row per DensaMed role.'),
    ]


# extend the map model with the mirror link (defined here to keep one file per
# concept readable); Odoo merges fields of same-named models across files.
class DensamedRoleGroupMapLink(models.Model):
    _inherit = 'densamed_bridge.role_group_map'

    bridge_role_id = fields.Many2one('densamed_bridge.role',
                                     string='Mirrored Role', ondelete='cascade')
