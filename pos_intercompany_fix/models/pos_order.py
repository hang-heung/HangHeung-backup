from odoo import models, api


class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _create_order_picking(self):
        # Run in sudo() so the procurement engine can traverse inter-company
        # stock routes (company_id=2, 3) without raising access errors for
        # single-company POS cashiers (e.g. ST1, company_id=1).
        # See: https://github.com/odoo/odoo/issues/22774
        return super(PosOrder, self.sudo())._create_order_picking()

    @api.model
    def sync_from_ui(self, orders):
        # pos_sale's sync_from_ui reads stock.picking records to update SO
        # delivery demands (cancelling/assigning waiting pickings). Wedding-
        # order Hoymay incoming pickings are hidden from Inventory Users via
        # the 'Hide wedding-chain Hoymay incoming pickings' ir.rule, which
        # raises AccessError when a cashier pays a deposit on a wedding SO.
        # sudo() bypasses the record rule -- session/cashier auth already
        # gates who can reach this endpoint.
        return super(PosOrder, self.sudo()).sync_from_ui(orders)
