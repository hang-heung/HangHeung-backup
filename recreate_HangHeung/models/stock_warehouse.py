from odoo import fields, models


class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    # HH-CUSTOM: widen the warehouse short code from the core 5-char limit
    # to 10 characters.
    code = fields.Char(size=10)
