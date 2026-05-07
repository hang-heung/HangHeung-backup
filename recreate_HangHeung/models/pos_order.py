"""POS order override for Hoymay's pre-order workflow.

Stock POS settlement (pos_sale.sync_from_ui) reduces a settled SO line's
stock-move demand by the qty just paid through POS, then cancels the
SO's outgoing picking when the demand goes to zero. That assumes POS
took the goods at the till -- correct for normal cash-and-carry, wrong
for HH's pre-order flow where POS is payment-only and the goods still
flow through the warehouse pickings.

Set a context flag on sync_from_ui; stock.picking.action_cancel and
stock.move.write detect it and refuse to touch HM/* pickings on the
Hoymay side. Pickings stay alive and only validate later when the
goods physically pass through.
"""
from odoo import api, models


class PosOrder(models.Model):
    _inherit = 'pos.order'

    @api.model
    def sync_from_ui(self, orders):
        return super(
            PosOrder, self.with_context(hh_pos_protect_hoymay_pickings=True)
        ).sync_from_ui(orders)
