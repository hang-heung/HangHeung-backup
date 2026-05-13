from odoo import _, api, fields, models


class PortalOrderControl(models.Model):
    """Per-portal-customer configuration for the Customer Portal order
    pages (上載購物紀錄 / 訂貨單). One record per partner; the partner
    becomes a portal customer eligible to use both portal pages.

    Drives:
    - which products show up in the portal product list
    - which pricelist is applied when a portal SO is created
    """
    _name = 'portal.order.control'
    _description = 'Portal Order Control'
    _rec_name = 'partner_id'
    _order = 'partner_id'

    partner_id = fields.Many2one(
        'res.partner',
        string='Portal Customer',
        required=True,
        ondelete='cascade',
        index=True,
        help="The portal user whose order pages this record controls. "
             "Must be a partner with portal access.",
    )
    pricelist_id = fields.Many2one(
        'product.pricelist',
        string='Pricelist',
        required=True,
        help="Applied to every sale.order created from this customer's "
             "portal pages (both 上載購物紀錄 and 訂貨單).",
    )
    product_ids = fields.Many2many(
        'product.product',
        'portal_order_control_product_rel',
        'control_id',
        'product_id',
        string='Allowed Products',
        domain=[('sale_ok', '=', True)],
        help="Only these products will appear on this customer's "
             "portal order pages.",
    )
    product_count = fields.Integer(
        compute='_compute_product_count',
        store=False,
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
    )
    note = fields.Text(string='Internal Note')

    _sql_constraints = [
        ('partner_unique',
         'unique(partner_id)',
         'Each portal customer can have only one Portal Order Control record.'),
    ]

    @api.depends('product_ids')
    def _compute_product_count(self):
        for rec in self:
            rec.product_count = len(rec.product_ids)

    def name_get(self):
        return [(rec.id, rec.partner_id.display_name) for rec in self]
