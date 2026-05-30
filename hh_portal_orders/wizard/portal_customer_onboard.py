import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

# Company routing for each order flow. Mirrors portal.order.control so the
# wizard and the control record always agree on which company a flow lives in.
CONSIGNEE_COMPANY_ID = 1   # Hoymay HK Ltd
CUSTOMER_COMPANY_ID = 3    # HANG HEUNG CAKE SHOP COMPANY LIMITED

_logger = logging.getLogger(__name__)


class PortalCustomerOnboardWizard(models.TransientModel):
    """One-stop onboarding for a portal order customer (網上落單客戶).

    Replaces the old three-app dance (Contacts -> Inventory warehouse
    wizard -> Sales Portal Order Control). From a single form the back
    office can:
      * pick (or inline-create) the contact,
      * set the portal login email + Fax-No. password,
      * for a consignee flow, spin up the consignee warehouse,
      * choose the pricelist + allowed products,
      * create the portal.order.control record (which auto-grants portal
        access).
    """
    _name = 'portal.customer.onboard.wizard'
    _description = 'Onboard Portal Customer'

    flow_type = fields.Selection(
        selection=[
            ('consignee', '寄賣倉訂貨 (Hoymay Consignee)'),
            ('customer', '客戶直接訂貨 (HangHeung Customer)'),
        ],
        string='Order Flow',
        required=True,
        default='consignee',
        help="寄賣倉訂貨 (Consignee): orders cascade through the "
             "intercompany chain (Hoymay -> That's -> HangHeung) and the "
             "customer also uploads day-end sales records.\n"
             "客戶直接訂貨 (Customer): orders become a direct HangHeung "
             "sale order.",
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        compute='_compute_company_id',
        store=True,
        readonly=True,
        help="Routed automatically from the Order Flow "
             "(Consignee -> Hoymay, Customer -> HangHeung).",
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Portal Customer',
        required=True,
        help="The contact who will log in to the portal order pages. "
             "Pick an existing contact or create one inline.",
    )
    login_email = fields.Char(
        string='Login Email',
        help="Used as the portal login. Saved back onto the contact.",
    )
    login_password = fields.Char(
        string='Password (Fax No.)',
        help="Used as the portal password. Saved onto the contact's "
             "Fax No. field. Treat as a shared secret.",
    )
    needs_warehouse = fields.Boolean(
        compute='_compute_existing_warehouse',
    )
    existing_warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Existing Warehouse',
        compute='_compute_existing_warehouse',
    )
    warehouse_code = fields.Char(
        string='Warehouse Short Code',
        size=10,
        help="Up to 10 characters; drives the picking-type prefixes. "
             "Only needed for a consignee with no warehouse yet.",
    )
    pricelist_id = fields.Many2one(
        'product.pricelist',
        string='Pricelist',
        required=True,
        help="Applied to every sale.order created from this customer's "
             "portal pages.",
    )
    product_ids = fields.Many2many(
        'product.product',
        string='Allowed Products',
        domain=[('sale_ok', '=', True)],
        help="Only these products appear on this customer's portal pages.",
    )
    note = fields.Text(string='Internal Note')

    @api.depends('flow_type')
    def _compute_company_id(self):
        for wiz in self:
            target = (CUSTOMER_COMPANY_ID if wiz.flow_type == 'customer'
                      else CONSIGNEE_COMPANY_ID)
            wiz.company_id = self.env['res.company'].browse(target)

    @api.depends('partner_id', 'company_id', 'flow_type')
    def _compute_existing_warehouse(self):
        Warehouse = self.env['stock.warehouse'].sudo()
        for wiz in self:
            wh = self.env['stock.warehouse']
            if wiz.flow_type == 'consignee' and wiz.partner_id and wiz.company_id:
                wh = Warehouse.search([
                    ('partner_id', '=', wiz.partner_id.id),
                    ('company_id', '=', wiz.company_id.id),
                ], limit=1)
            wiz.existing_warehouse_id = wh.id if wh else False
            # A consignee with no warehouse yet must supply a short code.
            wiz.needs_warehouse = bool(
                wiz.flow_type == 'consignee' and wiz.partner_id and not wh
            )

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        """Prefill the login email / password from the contact so the
        back office sees what's already on file before confirming."""
        for wiz in self:
            if wiz.partner_id:
                if not wiz.login_email:
                    wiz.login_email = (wiz.partner_id.email or '').strip()
                if not wiz.login_password:
                    wiz.login_password = (wiz.partner_id.fax_number or '').strip()

    def action_confirm(self):
        self.ensure_one()
        partner = self.partner_id
        if not partner:
            raise UserError(_("Please pick or create a Portal Customer contact."))

        email = (self.login_email or '').strip()
        password = (self.login_password or '').strip()
        if not email or not password:
            raise UserError(_(
                "Both a Login Email and a Password (Fax No.) are required to "
                "grant portal access."))

        # One control record per partner; fail early with a clear message
        # rather than tripping the SQL unique constraint later.
        existing_control = self.env['portal.order.control'].with_context(
            active_test=False).search([('partner_id', '=', partner.id)], limit=1)
        if existing_control:
            raise UserError(_(
                "'%s' already has a Portal Order Control record. Edit it from "
                "the customer list instead of onboarding again."
            ) % partner.display_name)

        # Persist the login credentials onto the contact. portal.order.control
        # ._grant_portal_access() reads email + fax_number from the partner.
        partner_vals = {}
        if (partner.email or '').strip() != email:
            partner_vals['email'] = email
        if (partner.fax_number or '').strip() != password:
            partner_vals['fax_number'] = password
        if partner_vals:
            partner.sudo().write(partner_vals)

        # Consignee with no warehouse yet -> create it via the existing wizard
        # so we reuse its uniqueness checks and picking-type setup.
        if self.flow_type == 'consignee' and self.needs_warehouse:
            code = (self.warehouse_code or '').strip()
            if not code:
                raise UserError(_(
                    "This consignee has no warehouse yet. Enter a Warehouse "
                    "Short Code so one can be created."))
            self.env['consignee.warehouse.wizard'].create({
                'partner_id': partner.id,
                'company_id': self.company_id.id,
                'warehouse_code': code,
            }).action_create_warehouse()

        # Creating the control record auto-grants portal access (login = email,
        # password = fax_number) via PortalOrderControl.create().
        control = self.env['portal.order.control'].create({
            'flow_type': self.flow_type,
            'partner_id': partner.id,
            'company_id': self.company_id.id,
            'pricelist_id': self.pricelist_id.id,
            'product_ids': [(6, 0, self.product_ids.ids)],
            'note': self.note or False,
        })

        return {
            'type': 'ir.actions.act_window',
            'name': _('Portal Order Control'),
            'res_model': 'portal.order.control',
            'res_id': control.id,
            'view_mode': 'form',
            'target': 'current',
        }
