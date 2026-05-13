import re

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import timedelta


SECURITY_CODE_PREFIXES = ('HHC', 'BWC', 'CWC', 'EWC', 'DPC', 'SWC', 'LWC')
SECURITY_CODE_TRAILING_DIGITS = 2


class LoyaltyCard(models.Model):
    _inherit = 'loyalty.card'

    prefix = fields.Char(string='Prefix', required=True, store=True)
    range_from = fields.Char(string='Range From', required=True, store=True)
    range_to = fields.Char(string='Range To', required=True, store=True)
    lot_id = fields.Many2one('stock.lot', string="Linked Lot")

    store_id = fields.Many2one('pos.config', string='Store')
    allocated_store_id = fields.Many2one('pos.config', string="Allocated Store", readonly=True)
    # HH-CUSTOM: which POS shop registered the activation of this coupon
    # (use_coupon_code). Populated forward from this version onward;
    # historical activated coupons keep this NULL.
    activation_store_id = fields.Many2one('pos.config', string="Activation Store", readonly=True)
    code = fields.Char(string='Code', readonly=True, required=False, copy=False,default=False)
    security_code = fields.Char(
        string='Security Code',
        copy=False,
        index=True,
        help=(
            "Optional secondary code scanned at redemption time for selected programs "
            "(prefixes HHC/BWC/CWC/EWC/DPC). Format: coupon code followed by exactly "
            "2 trailing digits (e.g. coupon HHC23000001 -> security HHC2300000122)."
        ),
    )

    _sql_constraints = [
        ('security_code_unique', 'UNIQUE (security_code)',
         'Security code must be unique across all loyalty cards.'),
    ]

    @api.constrains('security_code', 'code')
    def _check_security_code(self):
        for card in self:
            if not card.security_code:
                continue
            if not card.code:
                raise ValidationError(_(
                    "Security code cannot be set on a card without a coupon code."
                ))
            prefix = (card.code[:3] or '').upper()
            if prefix not in SECURITY_CODE_PREFIXES:
                raise ValidationError(_(
                    "Coupon '%(code)s' is not eligible for a security code "
                    "(prefix '%(prefix)s' not in allowed set: %(allowed)s).",
                    code=card.code, prefix=prefix,
                    allowed=', '.join(SECURITY_CODE_PREFIXES),
                ))
            pattern = re.escape(card.code) + r'\d{%d}' % SECURITY_CODE_TRAILING_DIGITS
            if not re.fullmatch(pattern, card.security_code):
                raise ValidationError(_(
                    "Security code '%(sec)s' is invalid for coupon '%(code)s'. "
                    "Expected: coupon code followed by exactly %(n)s digits.",
                    sec=card.security_code, code=card.code,
                    n=SECURITY_CODE_TRAILING_DIGITS,
                ))

    status = fields.Selection([
        ('not_activated', 'Not Activated'),
        ('activated', 'Activated'),
        ('invalid', 'Invalid'),
        ('redeemed', 'Redeemed'),
    ], string="Coupon Status", tracking=True, default='not_activated')

    date_activation = fields.Datetime(string="Activation Date", readonly=True)
    date_sale = fields.Datetime(string="Sale Date", readonly=True)
    redeem_shop_id = fields.Many2one('pos.config', string="Redeemed At", readonly=True)
    redeemed_datetime = fields.Datetime(string="Redeemed Date", readonly=True)

    remark = fields.Text(string='Internal Remark', help="Used for internal notes or memos. Not visible on printed coupon.")

    expiration_type = fields.Selection([
        ('fixed', 'Fixed Expiration Date'),
        ('post_activation', 'Valid after Activation'),
    ], string="Expiration Type", default='post_activation', required=True)

    validity_days = fields.Integer(string="Validity Duration (Days)", default=1825)

    effective_expiration = fields.Date(string="Effective Expiration", compute="_compute_dynamic_expiration_date", store=False)

    allocated_date = fields.Date(string='Allocated Date', readonly=True)

    sold_at_amount = fields.Float(
        string='Sold-At Amount',
        readonly=True,
        copy=False,
        help=(
            "Net amount actually paid by the customer at coupon-sale time "
            "(before any redemption). Drives the accounting split between "
            "240001 Receipts from Coupon (face value) and 240002 Redemption "
            "from Coupon (sell-time discount carry)."
        ),
    )

    face_value = fields.Float(
        string='Face Value',
        compute='_compute_face_value',
        store=False,
        help="Stated face value of this coupon (drawn from the program's product list price).",
    )

    discount_at_sale = fields.Float(
        string='Discount at Sale',
        compute='_compute_discount_at_sale',
        store=False,
        help="face_value - sold_at_amount. The portion that lands on 400010 Sales Discount at redeem time.",
    )

    @api.depends('program_id.product_id.lst_price')
    def _compute_face_value(self):
        for card in self:
            product = card.program_id.product_id
            card.face_value = product.lst_price if product else 0.0

    @api.depends('face_value', 'sold_at_amount')
    def _compute_discount_at_sale(self):
        for card in self:
            if card.sold_at_amount and card.face_value:
                card.discount_at_sale = card.face_value - card.sold_at_amount
            else:
                card.discount_at_sale = 0.0

    @api.model
    def create(self, vals):
        if vals.get('allocated_store_id') and not vals.get('allocated_date'):
            vals['allocated_date'] = fields.Date.today()
        return super().create(vals)

    def write(self, vals):
        if 'allocated_store_id' in vals and not vals.get('allocated_date'):
            vals['allocated_date'] = fields.Date.today()
        needs_lot_provisioning = (
            'allocated_store_id' in vals
            and vals.get('allocated_store_id')
            and 'lot_id' not in vals
        )
        result = super().write(vals)
        if needs_lot_provisioning:
            self._ensure_loyalty_lot_and_quant()
        return result

    def _ensure_loyalty_lot_and_quant(self):
        Lot = self.env['stock.lot'].sudo()
        Quant = self.env['stock.quant'].sudo()
        for card in self:
            if card.lot_id or not card.allocated_store_id:
                continue
            product = card.program_id.product_id
            if not product:
                continue
            store = card.allocated_store_id
            warehouse = store.picking_type_id.warehouse_id
            if not warehouse:
                continue
            location = warehouse.lot_stock_id or self.env.ref('stock.stock_location_stock')
            lot = Lot.search([
                ('name', '=', card.code),
                ('product_id', '=', product.id),
            ], limit=1)
            if not lot:
                lot = Lot.create({'name': card.code, 'product_id': product.id})
            quant_exists = Quant.search_count([
                ('product_id', '=', product.id),
                ('location_id', '=', location.id),
                ('lot_id', '=', lot.id),
            ])
            if not quant_exists:
                Quant.create({
                    'product_id': product.id,
                    'location_id': location.id,
                    'quantity': 1,
                    'lot_id': lot.id,
                })
            super(LoyaltyCard, card).write({'lot_id': lot.id})

    @api.depends('date_activation', 'validity_days', 'expiration_type')
    def _compute_dynamic_expiration_date(self):
        for record in self:
            if record.expiration_type == 'post_activation' and record.date_activation:
                record.effective_expiration = record.date_activation.date() + timedelta(days=record.validity_days)
            elif record.expiration_type == 'fixed':
                record.effective_expiration = record.expiration_date
            else:
                record.effective_expiration = False

    @api.model
    def create(self, vals):
        if vals.get('range_from') and vals.get('range_to') and vals.get('prefix'):
            try:
                range_from = int(vals['range_from'])
                range_to = int(vals['range_to'])
            except ValueError:
                raise ValidationError("Range From and Range To must be numeric.")

            if range_from > range_to:
                raise ValidationError("Range From cannot be greater than Range To.")

            number_length = max(len(vals['range_from']), len(vals['range_to']))
            created_cards = []

            for number in range(range_from, range_to + 1):
                code = f"{vals['prefix']}{str(number).zfill(number_length)}"
                card_vals = vals.copy()
                card_vals['code'] = code
                card_vals['range_from'] = str(number).zfill(number_length)
                card_vals['range_to'] = str(number).zfill(number_length)
                card = super(LoyaltyCard, self).create(card_vals)
                created_cards.append(card)

            return created_cards[0]
        else:
            return super(LoyaltyCard, self).create(vals)

    @api.model
    def update_loyalty_from_pos(self, product_data):
        for item in product_data:
            partner_id = item.get('customer_id')
            for lot_no in item.get('lots', []):
                card = self.search([('code', '=', lot_no)], limit=1)
                if card:
                    wizard = self.env['loyalty.card.update.balance'].create({
                        'card_id': card.id,
                        'old_balance': card.points_display,
                        'new_balance': 1,
                        'description': 'Updated from POS sale',
                    })
                    wizard.action_update_card_point()
                    vals = {
                        'status': 'activated',
                        'partner_id': partner_id or False,
                        'date_activation': fields.datetime.now(),
                    }
                    if not card.sold_at_amount:
                        sold_at = card._lookup_sold_at_from_pos()
                        if sold_at is not None:
                            vals['sold_at_amount'] = sold_at
                    card.write(vals)
        return True

    def _lookup_sold_at_from_pos(self):
        self.ensure_one()
        if not self.code:
            return None
        pack_lot = self.env['pos.pack.operation.lot'].sudo().search(
            [('lot_name', '=', self.code)],
            order='id desc',
            limit=1,
        )
        line = pack_lot.pos_order_line_id
        if line and line.qty:
            return line.price_subtotal_incl / line.qty
        return None

    @api.model
    def update_coupon_redeem_from_pos(self, vals):
        coupon_code = vals.get("coupon_code")
        store_id = vals.get("store_id")

        if coupon_code:
            card = self.search([('code', '=', coupon_code)])
            if card:
                card.write({
                    'redeem_shop_id': store_id,
                })
        return True

class LoyaltyHistory(models.Model):
    _inherit = 'loyalty.history'

    salesperson_id = fields.Many2one('res.users', string="Salesperson", readonly=True)
