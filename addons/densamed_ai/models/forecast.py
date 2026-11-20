"""A5 academic demo: simulated data, trained model, and Odoo stock comparison."""

import math
import os
from collections import defaultdict
from datetime import date, timedelta

import joblib
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import config

from .demo_data import read_demo_csv, write_demo_csv


def _features(code_number, day, index, history):
    previous = history[-7:]
    return [
        code_number, day.weekday(), day.month, index,
        history[-1], history[-7], sum(previous) / 7,
    ]


class AIForecastRun(models.Model):
    _name = 'densamed.ai.run'
    _description = 'AI Demand Forecast Demo Run'
    _order = 'id desc'

    name = fields.Char(default='New forecast', required=True)
    company_id = fields.Many2one('res.company', required=True,
                                 default=lambda self: self.env.company)
    warehouse_id = fields.Many2one('stock.warehouse', required=True,
                                   domain="[('company_id', '=', company_id)]")
    generated_at = fields.Datetime(readonly=True)
    source_label = fields.Char(default='SIMULATED CSV — academic demonstration', readonly=True)
    training_days = fields.Integer(readonly=True)
    product_count = fields.Integer(readonly=True)
    baseline_mae = fields.Float(string='Baseline MAE', readonly=True, digits=(12, 2))
    baseline_rmse = fields.Float(string='Baseline RMSE', readonly=True, digits=(12, 2))
    model_mae = fields.Float(string='Random Forest MAE', readonly=True, digits=(12, 2))
    model_rmse = fields.Float(string='Random Forest RMSE', readonly=True, digits=(12, 2))
    model_path = fields.Char(string='Saved model', readonly=True)
    forecast_ids = fields.One2many('densamed.ai.forecast', 'run_id', readonly=True)

    @api.model
    def _default_warehouse(self):
        return self.env['stock.warehouse'].search(
            [('company_id', '=', self.env.company.id)], limit=1)

    @api.model
    def default_get(self, field_list):
        values = super().default_get(field_list)
        if 'warehouse_id' in field_list and not values.get('warehouse_id'):
            warehouse = self._default_warehouse()
            if warehouse:
                values['warehouse_id'] = warehouse.id
        return values

    def action_generate(self):
        self.ensure_one()
        if not self.warehouse_id or self.warehouse_id.company_id != self.company_id:
            raise UserError(_('Choose a warehouse belonging to the selected branch.'))

        Product = self.env['product.product']
        products = Product.search([('product_tmpl_id.densamed_model', '=', 'medicines')],
                                  order='default_code', limit=20)
        if not products:
            # Reuse the team's bridge rather than creating a second product catalog.
            self.env['densamed.sync']._sync_products()
            products = Product.search([('product_tmpl_id.densamed_model', '=', 'medicines')],
                                      order='default_code', limit=20)
        products = products.filtered(lambda product: product.default_code)
        if not products:
            raise UserError(_('No synced DensaMed medicines are available.'))

        end_day = fields.Date.context_today(self) - timedelta(days=1)
        output_dir = os.path.join(config['data_dir'], 'ai_demo')
        os.makedirs(output_dir, exist_ok=True)
        csv_path = os.path.join(output_dir, 'salesdaily.csv')
        codes = products.mapped('default_code')
        write_demo_csv(csv_path, codes, end_day)
        series = read_demo_csv(csv_path)

        rows = []
        for code_number, code in enumerate(codes):
            observations = series[code]
            quantities = [quantity for _, quantity in observations]
            for index in range(7, len(observations)):
                day = date.fromisoformat(observations[index][0])
                rows.append((code, day, _features(code_number, day, index,
                                                   quantities[:index]), quantities[index]))

        cutoff = end_day - timedelta(days=14)
        train = [row for row in rows if row[1] <= cutoff]
        test = [row for row in rows if row[1] > cutoff]
        if not train or not test:
            raise UserError(_('The demo dataset is too short to evaluate.'))
        model = RandomForestRegressor(n_estimators=60, min_samples_leaf=2,
                                      random_state=42, n_jobs=1)
        model.fit([row[2] for row in train], [row[3] for row in train])
        actual = [row[3] for row in test]
        predicted = [max(0, value) for value in model.predict([row[2] for row in test])]
        baseline = [row[2][-1] for row in test]

        # Refit on all observed days after the chronological holdout evaluation.
        model.fit([row[2] for row in rows], [row[3] for row in rows])
        model_path = os.path.join(output_dir, 'forecast_model.joblib')
        joblib.dump({'model': model, 'product_codes': codes, 'trained_through': end_day.isoformat()},
                    model_path)

        self.forecast_ids.unlink()
        Forecast = self.env['densamed.ai.forecast']
        for code_number, product in enumerate(products):
            history = [quantity for _, quantity in series[product.default_code]]
            recent = sum(history[-7:]) / 7
            earlier = sum(history[-14:-7]) / 7
            daily = []
            for step in range(1, 8):
                day = end_day + timedelta(days=step)
                value = max(0, float(model.predict([
                    _features(code_number, day, len(history), history)
                ])[0]))
                daily.append(value)
                history.append(value)

            available = max(0, self.env['stock.quant']._get_available_quantity(
                product, self.warehouse_id.lot_stock_id))
            incoming = self._incoming_qty(product, end_day + timedelta(days=7))
            safety = max(0, product.min_stock)
            predicted_total = sum(daily)
            Forecast.create({
                'run_id': self.id,
                'company_id': self.company_id.id,
                'warehouse_id': self.warehouse_id.id,
                'product_id': product.id,
                'average_daily': recent,
                'trend_percent': 100 * (recent - earlier) / earlier if earlier else 0,
                'predicted_qty': predicted_total,
                'available_qty': available,
                'incoming_qty': incoming,
                'safety_stock': safety,
                'recommended_qty': max(0, math.ceil(predicted_total + safety - available - incoming)),
                **{'day_%s' % (i + 1): value for i, value in enumerate(daily)},
            })

        self.write({
            'name': 'AI demo forecast %s' % fields.Date.to_string(end_day + timedelta(days=1)),
            'generated_at': fields.Datetime.now(),
            'training_days': 120,
            'product_count': len(products),
            'baseline_mae': mean_absolute_error(actual, baseline),
            'baseline_rmse': math.sqrt(mean_squared_error(actual, baseline)),
            'model_mae': mean_absolute_error(actual, predicted),
            'model_rmse': math.sqrt(mean_squared_error(actual, predicted)),
            'model_path': model_path,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('AI Forecast Demo'),
            'res_model': self._name,
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'current',
        }

    def _incoming_qty(self, product, deadline):
        self.ensure_one()
        moves = self.env['stock.move'].search([
            ('product_id', '=', product.id),
            ('company_id', '=', self.company_id.id),
            ('state', 'in', ['confirmed', 'waiting', 'assigned', 'partially_available']),
            ('picking_id.picking_type_id.code', '=', 'incoming'),
            ('location_dest_id', 'child_of', self.warehouse_id.lot_stock_id.id),
            ('date', '<', fields.Datetime.to_string(deadline + timedelta(days=1))),
        ])
        return sum(moves.mapped('product_uom_qty'))


class AIForecast(models.Model):
    _name = 'densamed.ai.forecast'
    _description = 'Seven-Day Medicine Demand Forecast'
    _order = 'recommended_qty desc, id'

    run_id = fields.Many2one('densamed.ai.run', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one('res.company', required=True, index=True)
    warehouse_id = fields.Many2one('stock.warehouse', required=True)
    product_id = fields.Many2one('product.product', required=True)
    average_daily = fields.Float(readonly=True, digits=(12, 2))
    trend_percent = fields.Float(readonly=True, digits=(12, 1))
    predicted_qty = fields.Float(readonly=True, digits=(12, 2))
    available_qty = fields.Float(readonly=True, digits=(12, 2))
    incoming_qty = fields.Float(readonly=True, digits=(12, 2))
    safety_stock = fields.Float(readonly=True, digits=(12, 2))
    recommended_qty = fields.Float(readonly=True, digits=(12, 0))
    day_1 = fields.Float(readonly=True, digits=(12, 2))
    day_2 = fields.Float(readonly=True, digits=(12, 2))
    day_3 = fields.Float(readonly=True, digits=(12, 2))
    day_4 = fields.Float(readonly=True, digits=(12, 2))
    day_5 = fields.Float(readonly=True, digits=(12, 2))
    day_6 = fields.Float(readonly=True, digits=(12, 2))
    day_7 = fields.Float(readonly=True, digits=(12, 2))
