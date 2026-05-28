import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


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

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._grant_portal_access()
        return records

    def write(self, vals):
        res = super().write(vals)
        if vals.get('partner_id'):
            self._grant_portal_access()
        return res

    def copy(self, default=None):
        # The duplicated partner copies the original's email, which would
        # collide on the portal login. Skip the auto-grant for the copy;
        # access is granted later once a real (unique) partner is set.
        return super(
            PortalOrderControl, self.with_context(skip_portal_grant=True)
        ).copy(default)

    def _grant_portal_access(self):
        """Grant portal access to each record's partner, with
        login = partner.email and password = partner.fax_number."""
        if self.env.context.get('skip_portal_grant'):
            return
        portal_group = self.env.ref('base.group_portal')
        Users = self.env['res.users'].sudo()
        for rec in self:
            partner = rec.partner_id
            if not partner:
                continue
            login = (partner.email or '').strip()
            password = (partner.fax_number or '').strip()
            if not login or not password:
                raise UserError(_(
                    "Cannot grant portal access for '%s': the contact must have "
                    "both an Email (used as the login) and a Fax No. (used as the "
                    "password). Please fill them in on the contact first."
                ) % partner.display_name)

            existing = partner.sudo().user_ids[:1]
            if existing:
                if existing.has_group('base.group_portal') and not existing.has_group('base.group_user'):
                    existing.write({'login': login, 'password': password})
                else:
                    _logger.info(
                        "Portal grant skipped for %s: partner already has a "
                        "non-portal user (%s).", partner.display_name, existing.login)
                continue

            clash = Users.with_context(active_test=False).search(
                [('login', '=', login)], limit=1)
            if clash:
                raise UserError(_(
                    "Cannot grant portal access for '%s': the email '%s' is "
                    "already used as a login by another user. Use a unique email."
                ) % (partner.display_name, login))

            company = rec.company_id or self.env.company
            Users.with_context(no_reset_password=True).create({
                'login': login,
                'password': password,
                'partner_id': partner.id,
                'company_id': company.id,
                'company_ids': [(6, 0, [company.id])],
                'groups_id': [(6, 0, [portal_group.id])],
            })

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
