from odoo import models, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)

        if 'picking_type_id' not in fields_list:
            return res

        try:
            user = self.env.user.sudo()
            warehouse = user.property_warehouse_id

            if not warehouse:
                return res

            current_picking_type_id = res.get('picking_type_id')
            if not current_picking_type_id:
                return res

            current_type = self.env['stock.picking.type'].sudo().browse(current_picking_type_id)
            code = current_type.code

            matching_type = self.env['stock.picking.type'].sudo().search([
                ('warehouse_id', '=', warehouse.id),
                ('code', '=', code),
            ], limit=1)

            if matching_type:
                res['picking_type_id'] = matching_type.id
                if code == 'internal':
                    res['location_id'] = warehouse.lot_stock_id.id
                    res['location_dest_id'] = False

        except Exception as e:
            _logger.warning(
                'stock_user_warehouse_default: Failed to set default picking type '
                'for user %s: %s', self.env.user.name, str(e)
            )

        return res

    @api.onchange('location_id', 'location_dest_id')
    def _onchange_check_same_location(self):
        if (
            self.picking_type_id.code == 'internal'
            and self.location_id
            and self.location_dest_id
            and self.location_id == self.location_dest_id
        ):
            return {
                'warning': {
                    'title': '⚠️ 位置錯誤',
                    'message': (
                        '來源位置與目標位置不能相同！\n\n'
                        '來源：%s\n目標：%s\n\n'
                        '請選擇不同的目標位置。'
                    ) % (self.location_id.display_name, self.location_dest_id.display_name),
                }
            }
