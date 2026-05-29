from odoo import models, fields, api
from odoo.exceptions import ValidationError

HOYMAY_COMPANY_ID = 1


class HHMemberFreeRule(models.Model):
    _name = 'hh.member.free.rule'
    _description = '會員優惠規則 (買X送一)'
    _order = 'sequence, id'

    name = fields.Char(string='規則名稱', required=True)
    sequence = fields.Integer(default=10)
    qualifying_product_ids = fields.Many2many(
        'product.product',
        'hh_member_free_rule_product_rel',
        'rule_id', 'product_id',
        string='合資格產品',
        help="Products that count toward the threshold (explicit list).",
    )
    qualifying_category_ids = fields.Many2many(
        'product.category',
        'hh_member_free_rule_category_rel',
        'rule_id', 'category_id',
        string='合資格產品類別',
        help="A product also qualifies if its internal product category "
             "(or a sub-category) is listed here.",
    )
    threshold_qty = fields.Integer(
        string='所需數量 (X)',
        required=True,
        default=10,
        help="Accumulated qualifying units needed to grant one free product.",
    )
    free_product_ids = fields.Many2many(
        'product.product',
        'hh_member_free_rule_freeprod_rel',
        'rule_id', 'product_id',
        string='免費贈品',
        help="The member may pick one of these as the free gift.",
    )
    free_category_ids = fields.Many2many(
        'product.category',
        'hh_member_free_rule_freecat_rel',
        'rule_id', 'category_id',
        string='免費贈品類別',
        help="Any POS-sellable product in these categories (or sub-categories) "
             "is also offered as a free-gift choice.",
    )
    once_per_member = fields.Boolean(
        string='每位會員只可享用一次',
        default=False,
        help="If ticked, each member can be granted this promotion only once "
             "(lifetime).",
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        string='公司',
        required=True,
        default=lambda self: self.env['res.company'].browse(HOYMAY_COMPANY_ID),
    )

    @api.constrains('threshold_qty')
    def _check_threshold_qty(self):
        for rec in self:
            if rec.threshold_qty <= 0:
                raise ValidationError("所需數量 (X) 必須大於 0。")

    @api.constrains('free_product_ids', 'free_category_ids')
    def _check_free_gift_defined(self):
        for rec in self:
            if not rec.free_product_ids and not rec.free_category_ids:
                raise ValidationError("必須設定至少一項免費贈品（產品或類別）。")

    # ------------------------------------------------------------------
    # Resolved product sets
    # ------------------------------------------------------------------
    def _qualifying_category_ids_all(self):
        """All qualifying category IDs including descendants."""
        self.ensure_one()
        if not self.qualifying_category_ids:
            return []
        return self.env['product.category'].sudo().search([
            ('id', 'child_of', self.qualifying_category_ids.ids),
        ]).ids

    def _qualifying_product_ids_all(self):
        """Resolved qualifying products: explicit list + every product whose
        category (or a sub-category) is listed. Returned as IDs so the POS
        frontend can match purely by product id."""
        self.ensure_one()
        products = self.qualifying_product_ids
        cat_ids = self._qualifying_category_ids_all()
        if cat_ids:
            products |= self.env['product.product'].sudo().search([
                ('categ_id', 'in', cat_ids),
            ])
        return products.ids

    def _gift_product_ids(self):
        """Resolved gift pool: explicit products + POS-sellable products in
        the gift categories (incl. sub-categories), excluding combos."""
        self.ensure_one()
        products = self.free_product_ids
        if self.free_category_ids:
            cat_ids = self.env['product.category'].sudo().search([
                ('id', 'child_of', self.free_category_ids.ids),
            ]).ids
            products |= self.env['product.product'].sudo().search([
                ('categ_id', 'in', cat_ids),
                ('available_in_pos', '=', True),
                ('type', '!=', 'combo'),
            ])
        return products.filtered(lambda p: p.type != 'combo')

    def line_qualifies(self, product):
        """True if a product counts toward this rule's threshold."""
        self.ensure_one()
        if product.id in self.qualifying_product_ids.ids:
            return True
        if self.qualifying_category_ids and product.categ_id.id in self._qualifying_category_ids_all():
            return True
        return False

    # ------------------------------------------------------------------
    # POS payload
    # ------------------------------------------------------------------
    def _pos_rule_payload(self):
        """Compact dict the POS frontend uses to compute eligibility and to
        offer gift products."""
        self.ensure_one()
        return {
            'id': self.id,
            'name': self.name,
            'threshold_qty': self.threshold_qty,
            'once_per_member': self.once_per_member,
            'qualifying_product_ids': self._qualifying_product_ids_all(),
            'gift_product_ids': self._gift_product_ids().ids,
        }

    @api.model
    def get_pos_rules(self):
        """All active Hoymay rules as POS payloads."""
        rules = self.sudo().search([
            ('active', '=', True),
            ('company_id', '=', HOYMAY_COMPANY_ID),
        ])
        return [r._pos_rule_payload() for r in rules]
