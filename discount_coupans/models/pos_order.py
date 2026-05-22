from odoo import models, fields, _
from odoo.tools import float_repr, float_compare

class PosOrder(models.Model):
    _inherit = 'pos.order'

    def confirm_coupon_programs(self, coupon_data):
        """Extend base to mark coupon as redeemed when used."""
        result = super().confirm_coupon_programs(coupon_data)

        
        old_to_new_map = {cu['old_id']: cu['id'] for cu in result.get('coupon_updates', [])}
        points_map = {cu['id']: cu['points'] for cu in result.get('coupon_updates', [])}

       
        all_coupon_ids = set(points_map.keys()).union(
            [int(cid) for cid in coupon_data.keys() if int(cid) > 0]
        )

        coupons = self.env['loyalty.card'].browse(all_coupon_ids)

        for coupon in coupons:
            points = points_map.get(coupon.id) or coupon_data.get(str(coupon.id), {}).get('points', 0)

            if points <= 0 and coupon.status != 'redeemed' and int(coupon.points_display[0]) == 0:
                coupon.write({
                    'status': 'redeemed',
                    'redeemed_datetime': fields.Datetime.now(),
                    'redeem_shop_id': self.config_id.id,
                })

        return result

    def _prepare_invoice_lines(self):
        line_values_list = self._prepare_tax_base_line_values()
        invoice_lines = []

        for line_values in line_values_list:
            line = line_values['record']
            invoice_lines_values = self._get_invoice_lines_values(line_values, line)
            price_unit = invoice_lines_values.get("price_unit", 0.0)
            qty = invoice_lines_values.get("quantity", 0.0)
            subtotal = invoice_lines_values.get("price_subtotal", price_unit * qty)

            if float_compare(subtotal, 0.0, precision_rounding=self.currency_id.rounding) < 0:
                redeemed = True
                if "coupon_id" in line._fields and line.coupon_id:
                    redeemed = line.coupon_id.status in ("redeem", "redeemed", "used")
                elif "coupon_ids" in line._fields and line.coupon_ids:
                    redeemed = bool(line.coupon_ids.filtered(lambda c: c.status in ("redeem", "redeemed", "used")))

                if redeemed:
                    invoice_lines_values["name"] = _("Redeemed Coupon")
            if line.product_id.type == 'combo':
                quantity = int(invoice_lines_values['quantity']) if invoice_lines_values['quantity'] == int(invoice_lines_values['quantity']) else invoice_lines_values['quantity']
                invoice_lines.append((0, 0, {
                    'display_type': 'line_section',
                    'name': f'{line.product_id.name} x {quantity}',
                }))
                continue

            invoice_lines.append((0, 0, invoice_lines_values))

            is_percentage = self.pricelist_id and any(
                self.pricelist_id.item_ids.filtered(lambda rule: rule.compute_price == "percentage")
            )
            if is_percentage and float_compare(line.price_unit, line.product_id.lst_price, precision_rounding=self.currency_id.rounding) < 0:
                invoice_lines.append((0, 0, {
                    'name': _('Price discount from %(original_price)s to %(discounted_price)s',
                              original_price=float_repr(line.product_id.lst_price, self.currency_id.decimal_places),
                              discounted_price=float_repr(line.price_unit, self.currency_id.decimal_places)),
                    'display_type': 'line_note',
                }))

            if line.customer_note:
                invoice_lines.append((0, 0, {
                    'name': line.customer_note,
                    'display_type': 'line_note',
                }))

        if self.general_note:
            invoice_lines.append((0, 0, {
                'name': self['general_note'],
                'display_type': 'line_note',
            }))

        return invoice_lines

