from odoo import api, fields, models


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    def action_new_production_adjustment(self):
        """Open a blank hh.production.adj form from the Production Adjustment list."""
        return {
            'type': 'ir.actions.act_window',
            'name': 'New Production Adjustment',
            'res_model': 'hh.production.adj',
            'view_mode': 'form',
            'target': 'current',
            'context': self.env.context,
        }

    production_adjustment_qty = fields.Float(
        string='Adjustment (+/-)',
        compute='_compute_production_adjustment_qty',
        inverse='_inverse_production_adjustment_qty',
        digits='Product Unit of Measure',
        store=False,
        help="Type a positive number to add stock or a negative number to remove stock. "
             "Applied on top of the current On Hand quantity.",
    )

    @api.depends('inventory_quantity', 'quantity', 'inventory_quantity_set')
    def _compute_production_adjustment_qty(self):
        for quant in self:
            if quant.inventory_quantity_set:
                quant.production_adjustment_qty = quant.inventory_quantity - quant.quantity
            else:
                quant.production_adjustment_qty = 0.0

    def _inverse_production_adjustment_qty(self):
        for quant in self:
            quant.inventory_quantity = quant.quantity + quant.production_adjustment_qty
