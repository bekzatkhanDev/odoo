# -*- coding: utf-8 -*-
from datetime import timedelta
from collections import defaultdict
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare

class SalePromo(models.Model):
    _name = 'densamed.sale.promo'
    _description = 'Pharmacy Promotion Code'
    _order = 'id desc'
    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True, copy=False)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda s:s.env.company)
    discount_percent = fields.Float(required=True, default=5)
    min_amount = fields.Monetary(default=0)
    currency_id = fields.Many2one(related='company_id.currency_id')
    start_date = fields.Date()
    end_date = fields.Date()
    usage_limit = fields.Integer(help='0 means unlimited')
    used_count = fields.Integer(compute='_compute_usage')
    automatic = fields.Boolean(help='Apply automatically when minimum order amount is reached')
    @api.constrains('discount_percent','min_amount','usage_limit','start_date','end_date')
    def _check_promo(self):
        for r in self:
            if not 0 < r.discount_percent <= 100 or r.min_amount < 0 or r.usage_limit < 0 or (r.start_date and r.end_date and r.end_date < r.start_date):
                raise ValidationError(_('Invalid promotion configuration.'))
    @api.constrains('code','company_id')
    def _check_code(self):
        for r in self:
            if self.search_count([('code','=ilike',r.code.strip()),('company_id','=',r.company_id.id),('id','!=',r.id)]):
                raise ValidationError(_('Promotion code must be unique per branch.'))
    def _compute_usage(self):
        for r in self:
            r.used_count = self.env['densamed.sale'].search_count([('promo_id','=',r.id),('state','in',['completed','returned'])])
    def is_valid_for(self, sale, base):
        self.ensure_one()
        today=fields.Date.context_today(sale)
        return (self.active and self.company_id==sale.company_id and (not self.start_date or self.start_date<=today) and (not self.end_date or self.end_date>=today) and base>=self.min_amount and (not self.usage_limit or self.used_count<self.usage_limit))

class SaleExtended(models.Model):
    _inherit = 'densamed.sale'
    promo_id = fields.Many2one('densamed.sale.promo', string='Promotion', copy=False)
    promo_code = fields.Char(string='Promo Code', copy=False)
    promo_discount = fields.Monetary(compute='_compute_promo', store=True)
    loyalty_points_earned = fields.Integer(compute='_compute_loyalty', store=True)
    @api.depends('line_ids.subtotal','promo_id','promo_id.discount_percent')
    def _compute_promo(self):
        for s in self:
            base=sum(s.line_ids.mapped('subtotal'))
            s.promo_discount=s.currency_id.round(base*s.promo_id.discount_percent/100) if s.promo_id else 0
    @api.depends('amount_total')
    def _compute_loyalty(self):
        for s in self:
            s.loyalty_points_earned=max(0,int(s.amount_total//1000))
    @api.depends('line_ids.subtotal','promo_discount')
    @api.depends('line_ids.subtotal','promo_discount')
    def _compute_amount_total(self):
        for s in self:
            s.amount_total=max(0,sum(s.line_ids.mapped('subtotal'))-s.promo_discount)
    def action_apply_promo(self):
        for s in self:
            if s.state!='draft': raise UserError(_('Only draft sales can be discounted.'))
            base=sum(s.line_ids.mapped('subtotal'))
            promo=self.env['densamed.sale.promo'].search([('code','=ilike',(s.promo_code or '').strip()),('company_id','=',s.company_id.id)],limit=1)
            if not promo or not promo.is_valid_for(s,base): raise UserError(_('Promo code is invalid, expired, or has reached its limit.'))
            s.promo_id=promo
    def action_confirm(self):
        for s in self:
            base=sum(s.line_ids.mapped('subtotal'))
            if not s.promo_id:
                candidates=self.env['densamed.sale.promo'].search([('automatic','=',True),('company_id','=',s.company_id.id)],order='discount_percent desc')
                promo=next((p for p in candidates if p.is_valid_for(s,base)),False)
                if promo:s.promo_id=promo
            if s.promo_id and not s.promo_id.is_valid_for(s,base):
                raise UserError(_('Promotion is no longer valid.'))
        return super().action_confirm()

class PartnerSales(models.Model):
    _inherit='res.partner'
    pharmacy_sale_ids=fields.One2many('densamed.sale','partner_id',string='Pharmacy Purchases')
    pharmacy_sale_count=fields.Integer(compute='_compute_pharmacy_stats')
    pharmacy_spend=fields.Monetary(compute='_compute_pharmacy_stats',currency_field='currency_id')
    pharmacy_segment=fields.Selection([('new','New'),('regular','Regular'),('vip','VIP')],compute='_compute_pharmacy_stats')
    pharmacy_loyalty_points=fields.Integer(compute='_compute_pharmacy_stats')
    def _compute_pharmacy_stats(self):
        for p in self:
            sales=p.pharmacy_sale_ids.filtered(lambda s:s.state=='completed' and s.company_id==self.env.company)
            p.pharmacy_sale_count=len(sales)
            p.pharmacy_spend=sum(sales.mapped('amount_total'))
            p.pharmacy_loyalty_points=sum(sales.mapped('loyalty_points_earned'))
            p.pharmacy_segment='vip' if p.pharmacy_spend>=100000 or len(sales)>=20 else ('regular' if sales else 'new')
    def action_pharmacy_sales(self):
        self.ensure_one()
        return {'type':'ir.actions.act_window','name':_('Customer Purchases'),'res_model':'densamed.sale','view_mode':'tree,form','domain':[('partner_id','=',self.id)]}

class SalesDashboard(models.TransientModel):
    _name='densamed.sales.dashboard'
    _description='Sales Performance Dashboard'
    company_id=fields.Many2one('res.company',required=True,default=lambda s:s.env.company)
    date_from=fields.Date(required=True,default=lambda s:fields.Date.context_today(s)-timedelta(days=29))
    date_to=fields.Date(required=True,default=fields.Date.context_today)
    currency_id=fields.Many2one(related='company_id.currency_id')
    sale_count=fields.Integer(compute='_compute_metrics')
    revenue=fields.Monetary(compute='_compute_metrics')
    gross_profit=fields.Monetary(compute='_compute_metrics')
    units=fields.Integer(compute='_compute_metrics')
    average_ticket=fields.Monetary(compute='_compute_metrics')
    returns_count=fields.Integer(compute='_compute_metrics')
    @api.constrains('date_from','date_to')
    def _check_dates(self):
        for r in self:
            if r.date_to<r.date_from:raise ValidationError(_('End date must not precede start date.'))
    def _domain(self):
        self.ensure_one()
        return [('company_id','=',self.company_id.id),('date','>=',fields.Datetime.to_string(self.date_from)),('date','<',fields.Datetime.to_string(self.date_to+timedelta(days=1)))]
    def _compute_metrics(self):
        for r in self:
            sales=self.env['densamed.sale'].search(r._domain())
            done=sales.filtered(lambda x:x.state=='completed')
            r.sale_count=len(done);r.revenue=sum(done.mapped('amount_total'));r.gross_profit=sum(done.mapped('margin_total'))-sum(done.mapped('promo_discount'))
            r.units=sum(done.mapped('item_count'));r.average_ticket=r.revenue/len(done) if done else 0;r.returns_count=len(sales.filtered(lambda x:x.state=='returned'))
    def action_sales(self):
        self.ensure_one()
        return {'type':'ir.actions.act_window','name':_('Sales'),'res_model':'densamed.sale','view_mode':'tree,form,graph,pivot','domain':self._domain()}
    def action_lines(self):
        self.ensure_one()
        return {'type':'ir.actions.act_window','name':_('Top Medicines'),'res_model':'densamed.sale.line','view_mode':'graph,pivot,tree','domain':[('company_id','=',self.company_id.id),('date','>=',fields.Datetime.to_string(self.date_from)),('date','<',fields.Datetime.to_string(self.date_to+timedelta(days=1))),('state','=','completed')]}
    def action_print(self):
        return self.env.ref('densamed_sale_pro.action_report_dashboard').report_action(self)

class StockAlert(models.Model):
    _name='densamed.stock.alert'
    _description='Pharmacy Stock Threshold'
    _rec_name='product_id'
    product_id=fields.Many2one('product.product',required=True)
    warehouse_id=fields.Many2one('stock.warehouse',required=True,domain="[('company_id','=',company_id)]")
    company_id=fields.Many2one('res.company',required=True,default=lambda s:s.env.company)
    min_qty=fields.Float(default=10,required=True)
    available_qty=fields.Float(compute='_compute_qty')
    is_low=fields.Boolean(compute='_compute_qty')
    @api.constrains('min_qty')
    def _check_min(self):
        for r in self:
            if r.min_qty<0:raise ValidationError(_('Minimum quantity cannot be negative.'))
    @api.depends('product_id','warehouse_id','min_qty')
    def _compute_qty(self):
        for r in self:
            qty=self.env['stock.quant'].sudo()._get_available_quantity(r.product_id,r.warehouse_id.lot_stock_id) if r.product_id and r.warehouse_id else 0
            r.available_qty=qty;r.is_low=qty<r.min_qty
    def action_low_stock(self):
        ids=self.search([('company_id','in',self.env.companies.ids)]).filtered('is_low').ids
        return {'type':'ir.actions.act_window','name':_('Low Stock Alerts'),'res_model':self._name,'view_mode':'tree,form','domain':[('id','in',ids)]}

class SalesForecast(models.TransientModel):
    _name='densamed.sales.forecast'
    _description='Historical Sales Forecast'
    company_id=fields.Many2one('res.company',required=True,default=lambda s:s.env.company)
    lookback_days=fields.Integer(default=30,required=True)
    horizon_days=fields.Integer(default=7,required=True)
    currency_id=fields.Many2one(related='company_id.currency_id')
    historical_revenue=fields.Monetary(compute='_compute_forecast')
    forecast_revenue=fields.Monetary(compute='_compute_forecast')
    daily_average=fields.Monetary(compute='_compute_forecast')
    @api.constrains('lookback_days','horizon_days')
    def _check_days(self):
        for r in self:
            if not 1<=r.lookback_days<=365 or not 1<=r.horizon_days<=90:raise ValidationError(_('Lookback must be 1–365 days and horizon 1–90 days.'))
    def _compute_forecast(self):
        for r in self:
            cutoff=fields.Datetime.now()-timedelta(days=max(1,r.lookback_days))
            sales=self.env['densamed.sale'].search([('company_id','=',r.company_id.id),('state','=','completed'),('date','>=',fields.Datetime.to_string(cutoff))])
            r.historical_revenue=sum(sales.mapped('amount_total'))
            r.daily_average=r.historical_revenue/max(1,r.lookback_days)
            r.forecast_revenue=r.daily_average*max(1,r.horizon_days)
    def action_top_products(self):
        self.ensure_one()
        cutoff=fields.Datetime.now()-timedelta(days=self.lookback_days)
        return {'type':'ir.actions.act_window','name':_('Popular Medicines'),'res_model':'densamed.sale.line','view_mode':'graph,pivot,tree','domain':[('company_id','=',self.company_id.id),('state','=','completed'),('date','>=',fields.Datetime.to_string(cutoff))]}
