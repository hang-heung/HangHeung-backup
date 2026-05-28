from odoo import models, fields, api

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
    free_product_id = fields.Many2one(
        'product.product',
        string='免費贈品',
        required=True,
        ondelete='restrict',
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

    @api.constrains('threshold_qty')
    def _check_threshold_qty(self):
        from odoo.exceptions import ValidationError
        for rec in self:
            if rec.threshold_qty <= 0:
                raise ValidationError("所需數量 (X) 必須大於 0。")

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
        if any(k in vals for k in ('name', 'free_product_id', 'active', 'company_id')):
            for rule in self:
                rule._sync_loyalty_program()
        return res

    def _sync_loyalty_program(self):
        """Create or update the backing coupon program so a granted coupon
        gives one free unit of free_product_id at no charge, redeemable in
        POS."""
        self.ensure_one()
        if not self.free_product_id:
            return
        Program = self.env['loyalty.program'].sudo()
        prog_vals = {
            'name': f'[會員買X送一] {self.name}',
            'program_type': 'coupons',
            'trigger': 'with_code',
            'applies_on': 'current',
            'company_id': self.company_id.id,
            'active': self.active,
            # Make the coupon redeemable in POS. pos_config_ids left empty =
            # available in every POS session; the coupon is partner-bound so
            # it only applies when the issued member is the order's customer.
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
            self.env['loyalty.reward'].sudo().create({
                'program_id': prog.id,
                'reward_type': 'product',
                'reward_product_id': self.free_product_id.id,
                'reward_product_qty': 1,
                'required_points': 1,
            })
            self.with_context(skip_program_sync=True).loyalty_program_id = prog.id
        else:
            prog.write(prog_vals)
            reward = prog.reward_ids[:1]
            if reward:
                reward.sudo().write({
                    'reward_type': 'product',
                    'reward_product_id': self.free_product_id.id,
                    'reward_product_qty': 1,
                    'required_points': 1,
                })

    def _issue_free_coupon(self, partner):
        """Issue one free-product coupon (loyalty.card) to the member."""
        self.ensure_one()
        if not self.loyalty_program_id:
            self._sync_loyalty_program()
        if not self.loyalty_program_id:
            return self.env['loyalty.card']
        return self.env['loyalty.card'].sudo().create({
            'program_id': self.loyalty_program_id.id,
            'partner_id': partner.id,
            'points': 1,
        })
