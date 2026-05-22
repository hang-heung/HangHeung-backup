from odoo import models


class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _create_order_picking(self):
        # Run in sudo() so the procurement engine can traverse inter-company
        # stock routes (company_id=2, 3) without raising access errors for
        # single-company POS cashiers (e.g. ST1, company_id=1).
        # See: https://github.com/odoo/odoo/issues/22774
        return super(PosOrder, self.sudo())._create_order_picking()
