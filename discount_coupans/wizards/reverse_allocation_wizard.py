from odoo import models, fields, _


class LoyaltyReverseAllocationWizard(models.TransientModel):
    _name = "loyalty.reverse.allocation.wizard"
    _description = "Reverse Coupon Allocation (Bulk)"

    coupon_ids = fields.Many2many(
        'loyalty.card',
        string='Coupons',
        default=lambda self: [(6, 0, self.env.context.get('active_ids', []))],
    )
    force = fields.Boolean(
        string='Force on activated / redeemed / invalid',
        help="Reverse allocation even when the coupon is no longer in "
             "'Not Activated' status. Use only when you understand that "
             "this will desync the redemption-shop reports.",
    )
    summary = fields.Text(string='Result', readonly=True)

    def _reverse_one(self, card):
        if not card.allocated_store_id:
            return _('skipped: not allocated')
        if card.status != 'not_activated' and not self.force:
            return _('skipped: status=%s (tick Force to override)') % card.status

        old_store = card.allocated_store_id.name
        quants = card.lot_id.quant_ids.filtered(
            lambda q: q.location_id.usage == 'internal'
        )
        for q in quants:
            q.inventory_quantity = 0
            q.action_apply_inventory()

        card.write({
            'allocated_store_id': False,
            'allocated_date': False,
        })
        card.message_post(
            body=_("Allocation reversed from <b>%s</b>") % old_store
        )
        return _('reversed (was at %s)') % old_store

    def action_reverse(self):
        results = []
        for card in self.coupon_ids:
            results.append(f"{card.code}: {self._reverse_one(card)}")
        self.summary = '\n'.join(results)
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }
