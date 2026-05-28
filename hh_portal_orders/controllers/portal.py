import logging
from datetime import date, timedelta

from odoo import http, _
from odoo.exceptions import AccessError
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal

_logger = logging.getLogger(__name__)


HOYMAY_COMPANY_ID = 1
HANGHEUNG_COMPANY_ID = 3  # HANG HEUNG CAKE SHOP COMPANY LIMITED
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

    def _is_hangheung_control(self, control):
        """True when this Portal Order Control belongs to the HangHeung
        company. HangHeung consignees are treated as plain customers:
        no record-upload page, and their order creates a HangHeung SO
        with a normal customer delivery."""
        return bool(control) and control.company_id.id == HANGHEUNG_COMPANY_ID

    def _consignee_warehouse(self, control):
        """Return the consignee's own Hoymay warehouse (matched by the
        control's partner), or an empty recordset."""
        return request.env['stock.warehouse'].sudo().search([
            ('partner_id', '=', control.partner_id.id),
            ('company_id', '=', HOYMAY_COMPANY_ID),
        ], limit=1)

    def _convert_line_qty(self, product, entered_qty, post):
        """Resolve the chosen UoM for a product line and return
        (product_uom_id, qty_in_base_uom).

        The line is always stored in the product's base UoM. When the
        portal user picks the product's 'Alternate Unit of Measure', the
        entered quantity is converted to the base UoM by multiplying by
        the product's Conversion Rate (base_qty = entered * rate), since
        the alternate UoM is a free-form unit not tied to Odoo's UoM
        categories."""
        tmpl = product.product_tmpl_id
        choice = post.get('uom_%d' % product.id)
        if choice == 'alt' and tmpl.alternate_unit_of_measure and tmpl.conversion_rate:
            return product.uom_id.id, entered_qty * tmpl.conversion_rate
        return product.uom_id.id, entered_qty

    def _sorted_products(self, products):
        """Sort products by POS category name, then internal reference."""
        def key(p):
            cats = p.product_tmpl_id.pos_categ_ids.mapped('name')
            cat = sorted(cats)[0] if cats else 'zzz'
            return (cat, p.default_code or '', p.name or '')
        return products.sorted(key)

    def _grouped_products(self, products):
        """Group + sort products by POS category name. Returns a list of
        dicts {'code': str, 'name': str, 'products': [...]} ready for
        the template's category-header layout.

        HH category names embed a code prefix like 'H01 酥餅'. Split that
        into ('H01', '酥餅') for display. Names without a code prefix
        render with an empty code.

        Products without any pos_categ_ids are grouped under
        '其他 / Uncategorised' and shown last.
        """
        import re
        UNCATEGORISED = '其他 / Uncategorised'
        # Matches 'H01 ...', 'H123 ...', 'AA01 ...' etc.
        CODE_RE = re.compile(r'^\s*([A-Z][A-Z0-9]{1,5})\s+(.+?)\s*$')
        groups = {}
        for p in self._sorted_products(products):
            cats = p.product_tmpl_id.pos_categ_ids.mapped('name')
            label = sorted(cats)[0] if cats else UNCATEGORISED
            groups.setdefault(label, []).append(p)

        def split_code(label):
            if label == UNCATEGORISED:
                return ('', label)
            m = CODE_RE.match(label or '')
            if m:
                return (m.group(1), m.group(2))
            return ('', label)

        ordered = sorted(
            (groups.items()),
            key=lambda kv: (kv[0] == UNCATEGORISED, (kv[0] or '').lower()),
        )
        return [
            {'code': split_code(k)[0], 'name': split_code(k)[1], 'products': v}
            for k, v in ordered
        ]

    # ------------------------------------------------------------------
    # /my/upload-sales (上載購物紀錄)
    # ------------------------------------------------------------------

    @http.route('/my/upload-sales', type='http', auth='user', website=True)
    def portal_upload_sales(self, error=None, **kw):
        control = self._get_user_portal_control()
        if not control or self._is_hangheung_control(control):
            # HangHeung consignees have no record-upload page.
            return request.redirect('/my')
        products = self._sorted_products(control.product_ids)
        return request.render('hh_portal_orders.portal_upload_sales', {
            'control': control,
            'products': products,
            'grouped_products': self._grouped_products(control.product_ids),
            'page_title': '上載購物紀錄',
            'error': error,
        })

    @http.route('/my/upload-sales/submit', type='http', auth='user',
                website=True, methods=['POST'], csrf=True)
    def portal_upload_sales_submit(self, **post):
        control = self._get_user_portal_control()
        if not control or self._is_hangheung_control(control):
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

        products = {
            p.id: p for p in
            request.env['product.product'].sudo().browse(list(line_qty))
        }
        so_lines = []
        for pid, qty in line_qty.items():
            uom_id, base_qty = self._convert_line_qty(products[pid], qty, post)
            so_lines.append((0, 0, {
                'product_id': pid,
                'product_uom_qty': base_qty,
                'product_uom': uom_id,
            }))

        so_vals = {
            'partner_id': control.partner_id.id,
            'pricelist_id': control.pricelist_id.id,
            'company_id': HOYMAY_COMPANY_ID,
            'date_order': date_order + ' 12:00:00',
            'is_portal_record_upload': True,
            'order_line': so_lines,
        }
        # Consume stock from the consignee's own warehouse, if it has one.
        consignee_wh = self._consignee_warehouse(control)
        if consignee_wh:
            so_vals['warehouse_id'] = consignee_wh.id

        SO = request.env['sale.order'].sudo()
        try:
            so = SO.with_company(HOYMAY_COMPANY_ID).create(so_vals)
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
        page_title = '客戶訂貨單' if self._is_hangheung_control(control) else '訂貨單'
        return request.render('hh_portal_orders.portal_place_order', {
            'control': control,
            'products': products,
            'grouped_products': self._grouped_products(control.product_ids),
            'min_date': min_date,
            'page_title': page_title,
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

        products = {
            p.id: p for p in
            request.env['product.product'].sudo().browse(list(line_qty))
        }

        # ----------------------------------------------------------------
        # HangHeung consignees are plain customers: 客戶訂貨單 creates a
        # HangHeung sale.order to the portal customer with a normal
        # customer delivery (no own warehouse, no intercompany PO chain).
        # ----------------------------------------------------------------
        if self._is_hangheung_control(control):
            so_lines = []
            for pid, qty in line_qty.items():
                uom_id, base_qty = self._convert_line_qty(products[pid], qty, post)
                so_lines.append((0, 0, {
                    'product_id': pid,
                    'product_uom_qty': base_qty,
                    'product_uom': uom_id,
                }))
            # The SO is created in the HangHeung company, so the pricelist
            # must belong to HangHeung or be company-agnostic. The control's
            # pricelist may be a Hoymay one (incompatible) -- in that case
            # fall back to a HangHeung/company-agnostic pricelist.
            Pricelist = request.env['product.pricelist'].sudo()
            pricelist = control.pricelist_id
            if not pricelist or (pricelist.company_id and
                                 pricelist.company_id.id != HANGHEUNG_COMPANY_ID):
                pricelist = Pricelist.with_company(HANGHEUNG_COMPANY_ID).search([
                    ('company_id', 'in', (False, HANGHEUNG_COMPANY_ID)),
                ], order='company_id desc', limit=1)
            SO = request.env['sale.order'].sudo()
            try:
                so_vals = {
                    'partner_id': control.partner_id.id,
                    'company_id': HANGHEUNG_COMPANY_ID,
                    'commitment_date': commitment_date + ' 12:00:00',
                    'order_line': so_lines,
                }
                if pricelist:
                    so_vals['pricelist_id'] = pricelist.id
                so = SO.with_company(HANGHEUNG_COMPANY_ID).create(so_vals)
                so.with_company(HANGHEUNG_COMPANY_ID).action_confirm()
            except Exception as e:
                _logger.exception("Portal 客戶訂貨單 submit failed for partner %s: %s",
                                  control.partner_id.id, e)
                return request.redirect('/my/place-order?error=submit-failed')
            return request.redirect(so.get_portal_url())

        PO = request.env['purchase.order'].sudo()
        date_planned_str = commitment_date + ' 12:00:00'

        po_lines = []
        for pid, qty in line_qty.items():
            uom_id, base_qty = self._convert_line_qty(products[pid], qty, post)
            po_lines.append((0, 0, {
                'product_id': pid,
                'product_qty': base_qty,
                'product_uom': uom_id,
                'date_planned': date_planned_str,
            }))

        po_vals = {
            'company_id': HOYMAY_COMPANY_ID,
            'partner_id': THATS_VENDOR_PARTNER_ID,
            'date_planned': date_planned_str,
            'order_line': po_lines,
        }

        # Receive into the consignee's own warehouse (matched by partner).
        # Fall back to a dropship-to-consignee PO if no warehouse exists.
        consignee_wh = self._consignee_warehouse(control)
        if consignee_wh and consignee_wh.in_type_id:
            po_vals['picking_type_id'] = consignee_wh.in_type_id.id
        else:
            dropship_pt = request.env['stock.picking.type'].sudo().search([
                ('code', '=', 'dropship'),
                ('company_id', '=', HOYMAY_COMPANY_ID),
            ], limit=1)
            if not dropship_pt:
                _logger.error("Portal place-order: no Dropship picking type for Hoymay (company %s)",
                              HOYMAY_COMPANY_ID)
                return request.redirect('/my/place-order?error=submit-failed')
            po_vals['picking_type_id'] = dropship_pt.id
            po_vals['dest_address_id'] = control.partner_id.id

        try:
            po = PO.with_company(HOYMAY_COMPANY_ID).create(po_vals)
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
        values['hh_portal_is_hangheung'] = self._is_hangheung_control(control)
        return values

    # ------------------------------------------------------------------
    # 銷售紀錄 (/my/orders): a consignee may only see the Sales Orders they
    # submitted via 上載購物紀錄 (is_portal_record_upload=True), not other
    # orders that exist for their partner. Non-consignee portal users are
    # unaffected.
    # ------------------------------------------------------------------

    def _prepare_orders_domain(self, partner):
        domain = super()._prepare_orders_domain(partner)
        if self._get_user_portal_control():
            domain = domain + [('is_portal_record_upload', '=', True)]
        return domain
