from odoo import models


HOYMAY_COMPANY_ID = 1


class PosOrder(models.Model):
    _inherit = 'pos.order'

    def action_pos_order_paid(self):
        res = super().action_pos_order_paid()
        for order in self:
            if (
                order.partner_id
                and order.amount_total > 0
                and order.company_id.id == HOYMAY_COMPANY_ID
            ):
                order.partner_id._evaluate_tier()
        return res
