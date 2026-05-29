from odoo import models, fields


HOYMAY_COMPANY_ID = 1


class PosOrder(models.Model):
    _inherit = 'pos.order'

    def action_pos_order_paid(self):
        res = super().action_pos_order_paid()
        for order in self:
            if not (order.partner_id and order.company_id.id == HOYMAY_COMPANY_ID):
                continue
            # Tier re-evaluation (spending-based; ignore $0 orders)
            if order.amount_total > 0:
                order.partner_id._evaluate_tier()
            # Buy-X-get-free reconciliation — members (tier holders) only
            if order.partner_id.member_tier_id:
                order._reconcile_member_free_progress()
        return res

    def _reconcile_member_free_progress(self):
        """Update each rule's per-member carry-over counter from this order:
        add qualifying units purchased, subtract threshold per free gift given
        (flagged lines), and record grants. Free/reward lines never count as
        qualifying purchases."""
        self.ensure_one()
        partner = self.partner_id
        Rule = self.env['hh.member.free.rule'].sudo()
        Progress = self.env['hh.member.free.progress'].sudo()
        rules = Rule.search([
            ('active', '=', True),
            ('company_id', '=', HOYMAY_COMPANY_ID),
        ])
        for rule in rules:
            qualifying = 0
            free_given = 0
            for line in self.lines:
                if line.is_reward_line or line.hh_member_free_rule_id:
                    # Reward / member-free lines are never qualifying purchases.
                    if line.hh_member_free_rule_id == rule.id:
                        free_given += int(line.qty)
                    continue
                if line.qty > 0 and rule.line_qualifies(line.product_id):
                    qualifying += int(line.qty)

            if qualifying == 0 and free_given == 0:
                continue

            progress = Progress._get_or_create(partner, rule)
            new_acc = progress.accumulated_qty + qualifying - rule.threshold_qty * free_given
            progress.accumulated_qty = max(0, new_acc)
            if free_given:
                progress.grant_count += free_given
                progress.last_grant_date = fields.Datetime.now()
