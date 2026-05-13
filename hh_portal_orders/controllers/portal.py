import logging
from datetime import date, timedelta

from odoo import http, _
from odoo.exceptions import AccessError
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal

_logger = logging.getLogger(__name__)


HOYMAY_COMPANY_ID = 1
THATS_VENDOR_PARTNER_ID = 8883  # That's Ltd partner in Hoymay's books


class HHPortalOrders(CustomerPortal):

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_user_portal_control(self):
        """Return the portal.order.control record for the logged-in
        user's partner, or an empty recordset."""
        partner = request.env.user.partner_id.commercial_partner_id
        return request.env['portal.order.control'].sudo().search([
            '|', ('partner_id', '=', partner.id),
            ('partner_id', '=', request.env.user.partner_id.id),
            ('active', '=', True),
        ], limit=1)

    def _sorted_products(self, products):
        """Sort products by POS category name, then internal reference."""
        def key(p):
            cats = p.product_tmpl_id.pos_categ_ids.mapped('name')
            cat = sorted(cats)[0] if cats else 'zzz'
            return (cat, p.default_code or '', p.name or '')
        return products.sorted(key)

    # ------------------------------------------------------------------
    # /my/upload-sales (上載購物紀錄)
    # ------------------------------------------------------------------

    @http.route('/my/upload-sales', type='http', auth='user', website=True)
    def portal_upload_sales(self, error=None, **kw):
        control = self._get_user_portal_control()
        if not control:
            return request.render('hh_portal_orders.portal_no_access', {
                'page_title': '上載購物紀錄',
            })
        products = self._sorted_products(control.product_ids)
        return request.render('hh_portal_orders.portal_upload_sales', {
            'control': control,
            'products': products,
            'page_title': '上載購物紀錄',
            'error': error,
        })

    @http.route('/my/upload-sales/submit', type='http', auth='user',
                website=True, methods=['POST'], csrf=True)
    def portal_upload_sales_submit(self, **post):
        control = self._get_user_portal_control()
        if not control:
            return request.redirect('/my')

        date_order = (post.get('date_order') or '').strip()
        if not date_order:
            return request.redirect('/my/upload-sales?error=no-date')

        # Collect qty_<product_id> entries with positive numeric values
        # that belong to the allowed product set.
        allowed_ids = set(control.product_ids.ids)
        line_qty = {}
        for key, val in post.items():
            if not key.startswith('qty_'):
                continue
            try:
                pid = int(key[4:])
                qty = float(val or 0)
            except (TypeError, ValueError):
                continue
            if qty > 0 and pid in allowed_ids:
                line_qty[pid] = qty

        if not line_qty:
            return request.redirect('/my/upload-sales?error=no-qty')

        SO = request.env['sale.order'].sudo()
        try:
            so = SO.with_company(HOYMAY_COMPANY_ID).create({
                'partner_id': control.partner_id.id,
                'pricelist_id': control.pricelist_id.id,
                'company_id': HOYMAY_COMPANY_ID,
                'date_order': date_order + ' 12:00:00',
                'is_portal_record_upload': True,
                'order_line': [
                    (0, 0, {'product_id': pid, 'product_uom_qty': qty})
                    for pid, qty in line_qty.items()
                ],
            })
            so.with_company(HOYMAY_COMPANY_ID).action_confirm()
        except Exception as e:
            _logger.exception("Portal upload-sales submit failed for partner %s: %s",
                              control.partner_id.id, e)
            return request.redirect('/my/upload-sales?error=submit-failed')

        return request.redirect(f'/my/upload-sales/done/{so.id}')

    @http.route('/my/upload-sales/done/<int:so_id>', type='http',
                auth='user', website=True)
    def portal_upload_sales_done(self, so_id, **kw):
        so = request.env['sale.order'].sudo().browse(so_id).exists()
        partner = request.env.user.partner_id.commercial_partner_id
        if not so or so.partner_id not in (partner, request.env.user.partner_id):
            return request.redirect('/my')
        return request.render('hh_portal_orders.portal_upload_sales_done', {
            'so': so,
            'page_title': '上載購物紀錄 - 完成',
        })

    # ------------------------------------------------------------------
    # /my/place-order (訂貨單)
    # ------------------------------------------------------------------

    @http.route('/my/place-order', type='http', auth='user', website=True)
    def portal_place_order(self, error=None, **kw):
        control = self._get_user_portal_control()
        if not control:
            return request.render('hh_portal_orders.portal_no_access', {
                'page_title': '訂貨單',
            })
        products = self._sorted_products(control.product_ids)
        min_date = (date.today() + timedelta(days=1)).isoformat()
        return request.render('hh_portal_orders.portal_place_order', {
            'control': control,
            'products': products,
            'min_date': min_date,
            'page_title': '訂貨單',
            'error': error,
        })

    @http.route('/my/place-order/submit', type='http', auth='user',
                website=True, methods=['POST'], csrf=True)
    def portal_place_order_submit(self, **post):
        """Create a Hoymay PO with vendor=That's and
        dest_address=consignee. The standard intercompany rules + HH
        glue then propagate the chain to That's SO/PO and ultimately a
        HangHeung dropship delivery to the consignee."""
        control = self._get_user_portal_control()
        if not control:
            return request.redirect('/my')

        commitment_date = (post.get('commitment_date') or '').strip()
        if not commitment_date:
            return request.redirect('/my/place-order?error=no-date')

        try:
            req_date = date.fromisoformat(commitment_date)
        except ValueError:
            return request.redirect('/my/place-order?error=no-date')
        if req_date < date.today() + timedelta(days=1):
            return request.redirect('/my/place-order?error=date-too-soon')

        allowed_ids = set(control.product_ids.ids)
        line_qty = {}
        for key, val in post.items():
            if not key.startswith('qty_'):
                continue
            try:
                pid = int(key[4:])
                qty = float(val or 0)
            except (TypeError, ValueError):
                continue
            if qty > 0 and pid in allowed_ids:
                line_qty[pid] = qty

        if not line_qty:
            return request.redirect('/my/place-order?error=no-qty')

        PO = request.env['purchase.order'].sudo()
        date_planned_str = commitment_date + ' 12:00:00'
        try:
            po = PO.with_company(HOYMAY_COMPANY_ID).create({
                'company_id': HOYMAY_COMPANY_ID,
                'partner_id': THATS_VENDOR_PARTNER_ID,
                'dest_address_id': control.partner_id.id,
                'date_planned': date_planned_str,
                'order_line': [
                    (0, 0, {
                        'product_id': pid,
                        'product_qty': qty,
                        'date_planned': date_planned_str,
                    })
                    for pid, qty in line_qty.items()
                ],
            })
            po.with_company(HOYMAY_COMPANY_ID).button_confirm()
        except Exception as e:
            _logger.exception("Portal place-order submit failed for partner %s: %s",
                              control.partner_id.id, e)
            return request.redirect('/my/place-order?error=submit-failed')

        return request.redirect(f'/my/place-order/done/{po.id}')

    @http.route('/my/place-order/done/<int:po_id>', type='http',
                auth='user', website=True)
    def portal_place_order_done(self, po_id, **kw):
        po = request.env['purchase.order'].sudo().browse(po_id).exists()
        partner = request.env.user.partner_id.commercial_partner_id
        if not po or po.dest_address_id not in (partner, request.env.user.partner_id):
            return request.redirect('/my')
        return request.render('hh_portal_orders.portal_place_order_done', {
            'po': po,
            'page_title': '訂貨單 - 完成',
        })

    # ------------------------------------------------------------------
    # /my -- Portal home: surface the two big tiles when the user has a
    # portal.order.control record.
    # ------------------------------------------------------------------

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        control = self._get_user_portal_control()
        values['hh_portal_control'] = control
        return values
