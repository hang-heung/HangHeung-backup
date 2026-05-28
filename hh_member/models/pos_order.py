from odoo import models, fields


HOYMAY_COMPANY_ID = 1


class PosOrder(models.Model):
    _inherit = 'pos.order'

    def action_pos_order_paid(self):
        res = super().action_pos_order_paid()
        for order in self:
            if not (
                order.partner_id
                and order.amount_total > 0
                and order.company_id.id == HOYMAY_COMPANY_ID
            ):
                continue
            # 1) membership tier re-evaluation
            order.partner_id._evaluate_tier()
            # 2) buy-X-get-free accumulation — members (tier holders) only
            if order.partner_id.member_tier_id:
                order._accumulate_free_product_progress()
        return res

    def _accumulate_free_product_progress(self):
        """Add this order's qualifying units to each active rule's per-member
        accumulator, and issue a free-product coupon every time the threshold
        is crossed (counter reset by threshold on each grant)."""
        self.ensure_one()
        partner = self.partner_id
        Rule = self.env['hh.member.free.rule'].sudo()
        Progress = self.env['hh.member.free.progress'].sudo()
        rules = Rule.search([
            ('active', '=', True),
            ('company_id', '=', HOYMAY_COMPANY_ID),
        ])
        for rule in rules:
            qty = self._count_qualifying_units(rule)
            if qty <= 0:
                continue
            progress = Progress._get_or_create(partner, rule)
            progress.accumulated_qty += qty
            while rule.threshold_qty > 0 and progress.accumulated_qty >= rule.threshold_qty:
                rule._issue_free_coupon(partner)
                progress.accumulated_qty -= rule.threshold_qty
                progress.grant_count += 1
                progress.last_grant_date = fields.Datetime.now()

    def _count_qualifying_units(self, rule):
        """Sum the units of qualifying products in this order's non-reward
        lines. A product qualifies if it is in the rule's explicit product
        list, or its internal category (or a sub-category) is listed."""
        self.ensure_one()
        categ_ids = set()
        if rule.qualifying_category_ids:
            categ_ids = set(self.env['product.category'].sudo().search([
                ('id', 'child_of', rule.qualifying_category_ids.ids),
            ]).ids)
        product_ids = set(rule.qualifying_product_ids.ids)
        total = 0.0
        for line in self.lines:
            if line.is_reward_line:
                continue
            prod = line.product_id
            if prod.id in product_ids or prod.categ_id.id in categ_ids:
                total += line.qty
        return int(total) if total > 0 else 0
