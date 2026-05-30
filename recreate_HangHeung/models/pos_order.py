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

    @api.model
    def search_paid_order_ids(self, config_id, domain, limit, offset):
        # Standard Odoo strips the config_id filter as soon as the
        # frontend supplies a search domain, which means a cashier on
        # one store can see another store's orders in the search
        # results -- and the limit-30 paging then pushes their own
        # store's older orders out of reach. Always anchor the search
        # to the calling config_id.
        domain = list(domain or [])
        if not any(
            isinstance(c, (list, tuple)) and len(c) == 3 and c[0] == 'config_id'
            for c in domain
        ):
            domain = [('config_id', '=', config_id)] + domain
        return super().search_paid_order_ids(config_id, domain, limit, offset)
