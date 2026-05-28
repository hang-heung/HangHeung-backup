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
    warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Consignee Warehouse',
        compute='_compute_warehouse_id',
        store=False,
        help="The consignee warehouse linked to this customer "
             "(matched by partner and company).",
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

    @api.depends('partner_id', 'company_id')
    def _compute_warehouse_id(self):
        Warehouse = self.env['stock.warehouse'].sudo()
        for rec in self:
            wh = self.env['stock.warehouse']
            if rec.partner_id:
                domain = [('partner_id', '=', rec.partner_id.id)]
                if rec.company_id:
                    domain.append(('company_id', '=', rec.company_id.id))
                wh = Warehouse.search(domain, limit=1)
            rec.warehouse_id = wh.id if wh else False

    def copy_data(self, default=None):
        default = dict(default or {})
        vals_list = super().copy_data(default=default)
        # The partner_unique constraint forbids two control records on the
        # same partner, so a plain duplicate would fail. Instead, copy the
        # partner too (res.partner.copy names it "<name> (copy)") and point
        # the duplicated control record at that new partner.
        if 'partner_id' not in default:
            for rec, vals in zip(self, vals_list):
                if rec.partner_id:
                    vals['partner_id'] = rec.partner_id.copy().id
        return vals_list

    def name_get(self):
        return [(rec.id, rec.partner_id.display_name) for rec in self]
