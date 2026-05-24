import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


def _is_hoymay_so_picking(picking):
    """True when this picking belongs to the Hoymay-side of an SO chain
    that POS settlement must NOT cancel/zero in our pre-order workflow.
    Matches HM/* origins (HM SO outgoing OR Hoymay incoming whose origin
    is the Hoymay PO name like 'HM/Pxxxxx')."""
    if not picking or picking.company_id.id != 1:
        return False
    origin = picking.origin or ''
    return origin.startswith('HM/')


class StockMove(models.Model):
    _inherit = 'stock.move'

    @api.model_create_multi
    def create(self, vals_list):
        # HH-CUSTOM: if a fresh stock.move lands on a draft picking,
        # action_confirm the picking so it doesn't sit in draft after
        # procurement adds moves later. The existing stock.picking.create
        # hook only fires action_confirm at picking-creation time and
        # misses pickings that get moves attached afterwards.
        moves = super().create(vals_list)
        if not self.env.context.get('skip_auto_confirm'):
            for picking in moves.mapped('picking_id'):
                if picking.state == 'draft' and picking.move_ids:
                    try:
                        picking.action_confirm()
                    except Exception as e:
                        _logger.warning(
                            "Auto-confirm skipped for picking %s on stock.move.create: %s",
                            picking.name or '?', e,
                        )
        return moves

    def write(self, vals):
        # HH-CUSTOM: when POS sync_from_ui tries to zero out the demand on
        # Hoymay SO pickings, leave product_uom_qty alone -- the goods still
        # need to flow through the warehouse picking chain (POS only took
        # payment, not delivery).
        if (
            self.env.context.get('hh_pos_protect_hoymay_pickings')
            and 'product_uom_qty' in vals
        ):
            protected = self.filtered(lambda m: _is_hoymay_so_picking(m.sudo().picking_id))
            unprotected = self - protected
            other_vals = {k: v for k, v in vals.items() if k != 'product_uom_qty'}
            res = True
            if protected and other_vals:
                res = super(StockMove, protected).write(other_vals)
            if unprotected:
                res = super(StockMove, unprotected).write(vals) and res
            return res
        return super().write(vals)

    def _get_product_catalog_lines_data(self, parent_record=None, **kwargs):
        return {
            'quantity': sum(self.mapped('product_uom_qty')),
            'price': 0.0,
            'readOnly': parent_record._is_readonly() if parent_record else False,
        }

    def action_add_from_catalog(self):
        picking = self.env['stock.picking'].browse(self.env.context.get('order_id'))
        return picking.with_context(child_field='move_ids_without_package').action_add_from_catalog()
