from odoo import models, fields, api
from odoo.exceptions import ValidationError

HOYMAY_COMPANY_ID = 1


class HHMemberFreeRule(models.Model):
    _name = 'hh.member.free.rule'
    _description = '會員買X送一規則'
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
    # ── Free gift: explicit products and/or a category pool ──────────────
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
             "(lifetime). After the first free product, the member can never "
             "use this rule again.",
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        string='公司',
        required=True,
        default=lambda self: self.env['res.company'].browse(HOYMAY_COMPANY_ID),
    )
    loyalty_program_id = fields.Many2one(
        'loyalty.program',
        string='優惠券計劃',
        readonly=True,
        copy=False,
        help="Auto-managed coupon program that delivers the free product "
             "when a granted coupon is applied in POS.",
    )
    gift_tag_id = fields.Many2one(
        'product.tag',
        string='贈品產品標籤',
        readonly=True,
        copy=False,
        help="Auto-managed product tag that holds the gift pool when more "
             "than one free product is offered (Odoo loyalty multi-product "
             "rewards are tag-driven).",
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
    # Free-gift product pool (explicit + category-expanded)
    # ------------------------------------------------------------------
    def _reward_product_recordset(self):
        """Resolve the set of products offered as the free gift: the explicit
        list plus every POS-sellable product whose category (or a
        sub-category) is in free_category_ids. Combo products are excluded —
        Odoo loyalty rewards reject reward_type='product' combos."""
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

    # ------------------------------------------------------------------
    # Backing loyalty.program (coupon, free-product reward)
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        rules = super().create(vals_list)
        for rule in rules:
            rule._sync_loyalty_program()
        return rules

    def write(self, vals):
        res = super().write(vals)
        sync_keys = ('name', 'free_product_ids', 'free_category_ids',
                     'active', 'company_id')
        if any(k in vals for k in sync_keys):
            for rule in self:
                rule._sync_loyalty_program()
        return res

    def _ensure_gift_tag(self):
        """Return (creating if needed) the dedicated product.tag used to hold
        the gift pool for multi-product rewards."""
        self.ensure_one()
        Tag = self.env['product.tag'].sudo()
        name = f'[會員贈品] {self.name}'
        tag = self.gift_tag_id
        if not tag:
            tag = Tag.create({'name': name})
            self.with_context(skip_program_sync=True).gift_tag_id = tag.id
        elif tag.name != name:
            tag.write({'name': name})
        return tag

    def _sync_loyalty_program(self):
        """Create or update the backing coupon program. The reward is a free
        product; when more than one product is offered, a dedicated product
        tag drives Odoo's multi-product (cashier-choice) reward."""
        self.ensure_one()
        reward_products = self._reward_product_recordset()
        if not reward_products:
            return

        reward_vals = {
            'reward_type': 'product',
            'reward_product_id': reward_products[0].id,
            'reward_product_qty': 1,
            'required_points': 1,
        }
        if len(reward_products) > 1:
            tag = self._ensure_gift_tag()
            tag.sudo().write({
                'product_template_ids': [(6, 0, reward_products.product_tmpl_id.ids)],
            })
            reward_vals['reward_product_tag_id'] = tag.id
        else:
            reward_vals['reward_product_tag_id'] = False

        Program = self.env['loyalty.program'].sudo()
        prog_vals = {
            'name': f'[會員買X送一] {self.name}',
            'program_type': 'coupons',
            'trigger': 'with_code',
            'applies_on': 'current',
            'company_id': self.company_id.id,
            'active': self.active,
            # Redeemable in every POS session; coupon is partner-bound.
            'pos_ok': True,
        }
        prog = self.loyalty_program_id
        if not prog:
            prog = Program.create(prog_vals)
            self.env['loyalty.rule'].sudo().create({
                'program_id': prog.id,
                'reward_point_amount': 1,
                'reward_point_mode': 'order',
                'minimum_qty': 0,
                'minimum_amount': 0.0,
            })
            reward_vals['program_id'] = prog.id
            self.env['loyalty.reward'].sudo().create(reward_vals)
            self.with_context(skip_program_sync=True).loyalty_program_id = prog.id
        else:
            prog.write(prog_vals)
            reward = prog.reward_ids[:1]
            if reward:
                reward.sudo().write(reward_vals)

    def _issue_free_coupon(self, partner):
        """Refresh the gift pool (catches new category products) and issue one
        free-product coupon (loyalty.card) to the member."""
        self.ensure_one()
        self._sync_loyalty_program()
        if not self.loyalty_program_id:
            return self.env['loyalty.card']
        return self.env['loyalty.card'].sudo().create({
            'program_id': self.loyalty_program_id.id,
            'partner_id': partner.id,
            'points': 1,
        })
