from odoo import _, fields, models
from odoo.exceptions import UserError
from datetime import timedelta
import logging

_logger = logging.getLogger(__name__)

# Programs that use the security-code mechanism. The first 3 letters of a
# scanned code must be in this set for the security_code OR-branch to fire.
SECURITY_CODE_PREFIXES = ('HHC', 'BWC', 'CWC', 'EWC', 'DPC', 'SWC', 'LWC')


class PosConfig(models.Model):
    _inherit = 'pos.config'

    def use_coupon_code(self, code, creation_date, partner_id, pricelist_id):
        self.ensure_one()
        # Only enable the security_code lookup when the scanned code starts
        # with one of the eligible 3-letter prefixes. For any other code,
        # behave exactly like the original lookup-by-code-only path.
        prefix = (code or '')[:3].upper()
        if prefix in SECURITY_CODE_PREFIXES:
            domain = [
                ('program_id', 'in', self._get_program_ids().ids),
                '|', ('code', '=', code), ('security_code', '=', code),
                '|', ('partner_id', 'in', (False, partner_id)), ('program_type', '=', 'gift_card'),
            ]
        else:
            domain = [
                ('program_id', 'in', self._get_program_ids().ids),
                ('code', '=', code),
                '|', ('partner_id', 'in', (False, partner_id)), ('program_type', '=', 'gift_card'),
            ]
        coupon = self.env['loyalty.card'].search(domain, order='partner_id, points desc', limit=1)

        program = coupon.program_id

        if not coupon or not program or not program.active:
            return {
                'successful': False,
                'payload': {
                    'error_message': _('This coupon is invalid (%s).', code),
                },
            }

        if coupon.store_id and coupon.store_id.id != self.id:
            _logger.warning("Coupon %s is not valid in store %s (expected store %s)", coupon.code, self.id, coupon.store_id.id)
            return {
                'successful': False,
                'payload': {
                    'error_message': _('This coupon is not valid for this store.'),
                },
            }

        if coupon.status == 'activated' and int(coupon.points_display[0]) == 0:
            return {
                'successful': False,
                'payload': {
                    'error_message': _('No reward can be claimed with this coupon.'),
                },
            }

        if coupon.status == 'invalid':
            return {
                'successful': False,
                'payload': {
                    'error_message': _('This coupon is marked as invalid.'),
                },
            }

        check_date = fields.Date.from_string(creation_date[:10])
        today_date = fields.Date.context_today(self)

        if coupon.expiration_type == 'fixed':
            expiration = coupon.expiration_date
        elif coupon.expiration_type == 'post_activation':
            activation_date = coupon.date_activation.date() if coupon.date_activation else check_date
            expiration = activation_date + timedelta(days=coupon.validity_days)
        else:
            expiration = None

        error_message = False
        if expiration and expiration < check_date:
            error_message = _("This coupon is expired (%s).", code)
        elif program.date_from and program.date_from.date() > today_date:
            error_message = _("This coupon is not yet valid (%s).", code)
        elif program.date_to and program.date_to.date() < today_date:
            error_message = _("This program is no longer active (%s).", code)
        elif program.limit_usage and program.sudo().total_order_count >= program.max_usage:
            error_message = _("This coupon program has reached its maximum usage.")
        elif not program.reward_ids or not any(r.required_points <= coupon.points for r in program.reward_ids):
            error_message = _("No reward can be claimed with this coupon.")
        elif program.pricelist_ids and pricelist_id not in program.pricelist_ids.ids:
            error_message = _("This coupon is not available with the current pricelist.")
        elif program.program_type == 'promo_code':
            error_message = _("This program requires a code to be applied.")

        if error_message:
            return {
                'successful': False,
                'payload': {
                    'error_message': error_message,
                },
            }

        coupon.write({
            'status': 'activated',
            'date_activation': fields.Datetime.now(),
            'date_sale': fields.Datetime.now(),
            # HH-CUSTOM: track which POS shop scanned/activated the coupon
            # so reports can show Activation Store alongside Redeem Store.
            'activation_store_id': self.id,
        })

        return {
            'successful': True,
            'payload': {
                'program_id': program.id,
                'coupon_id': coupon.id,
                'partner_id': coupon.partner_id.id if coupon.partner_id else False,
                'points': coupon.points,
                'has_source_order': coupon._has_source_order(),
            },
        }
