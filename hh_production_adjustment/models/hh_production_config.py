from odoo import _, fields, models
from odoo.exceptions import ValidationError


class HhProductionConfig(models.Model):
    _name = 'hh.production.config'
    _description = 'Production Order Configuration (per company)'
    _rec_name = 'company_id'

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, ondelete='cascade',
        default=lambda self: self.env.company,
    )
    consume_type_id = fields.Many2one(
        'stock.picking.type', string='Consumption Operation Type', required=True,
        domain="[('code', '=', 'internal')]",
        help="Operation type used to consume raw materials (stock → virtual production location).",
    )
    output_type_id = fields.Many2one(
        'stock.picking.type', string='Output Operation Type', required=True,
        domain="[('code', '=', 'internal')]",
        help="Operation type used to add produced goods (virtual production location → stock).",
    )

    _sql_constraints = [
        ('company_uniq', 'unique(company_id)', 'A production configuration already exists for this company.'),
    ]
