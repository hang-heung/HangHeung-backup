# -*- coding: utf-8 -*-
import pytz
from datetime import datetime
from odoo import api, models


class ReportSaleDetails(models.AbstractModel):
    _inherit = 'report.point_of_sale.report_saledetails'

    @api.model
    def get_sale_details(self, date_start=False, date_stop=False,
                         config_ids=False, session_ids=False, **kwargs):
        result = super().get_sale_details(
            date_start, date_stop, config_ids, session_ids, **kwargs
        )

        # ── 1. Store short code (part before " - ") ───────────────────────
        result['config_names'] = [
            n.split(' - ')[0].strip() if ' - ' in n else n
            for n in result.get('config_names', [])
        ]

        # ── 2. Date-only strings in HKT ───────────────────────────────────
        user_tz = pytz.timezone(
            self.env.context.get('tz') or self.env.user.tz or 'Asia/Hong_Kong'
        )

        def _fmt(dt):
            """Format a UTC datetime (naive or aware, or string) as 年月日 in user TZ."""
            if not dt:
                return ''
            if isinstance(dt, str):
                dt = datetime.strptime(dt, '%Y-%m-%d %H:%M:%S')
            # BUG FIX: handle both naive (assume UTC) and tz-aware datetimes
            if dt.tzinfo is None:
                dt = pytz.utc.localize(dt)
            dt = dt.astimezone(user_tz)
            return dt.strftime('%Y年%m月%d日')

        ds = _fmt(result.get('date_start'))
        de = _fmt(result.get('date_stop'))
        result['date_start_str'] = ds
        result['date_stop_str']  = de if de != ds else ''

        # ── 3. Consolidate duplicate rows (same product, different price/discount)
        def _consolidate(categories):
            for cat in categories:
                merged = {}
                for p in cat.get('products', []):
                    # BUG FIX: key by product_id (not product_name) so two
                    # different products that happen to share a display name
                    # are never collapsed into one row.
                    key = p['product_id']
                    if key not in merged:
                        merged[key] = dict(p)
                        merged[key]['discount'] = 0
                    else:
                        merged[key]['quantity']    += p['quantity']
                        merged[key]['base_amount'] += p['base_amount']
                        merged[key]['total_paid']  += p['total_paid']
                cat['products'] = sorted(
                    merged.values(), key=lambda x: x['product_name']
                )
                cat['qty']   = sum(p['quantity']    for p in cat['products'])
                cat['total'] = sum(p['base_amount'] for p in cat['products'])
            return categories

        result['products']        = _consolidate(result.get('products', []))
        result['refund_products'] = _consolidate(result.get('refund_products', []))

        # Recalculate totals after consolidation
        result['products_info'] = {
            'qty':   sum(p['quantity']    for c in result['products'] for p in c['products']),
            'total': sum(p['base_amount'] for c in result['products'] for p in c['products']),
        }
        result['refund_info'] = {
            'qty':   sum(p['quantity']    for c in result['refund_products'] for p in c['products']),
            'total': sum(p['base_amount'] for c in result['refund_products'] for p in c['products']),
        }

        # ── 4. Split goods (positive total) vs service/discount (negative) ─
        goods    = [c for c in result['products'] if c['total'] >= 0]
        services = [c for c in result['products'] if c['total'] <  0]
        result['goods_products']   = goods
        result['service_products'] = services
        result['goods_info'] = {
            'qty':   sum(p['quantity']    for c in goods    for p in c['products']),
            'total': sum(p['base_amount'] for c in goods    for p in c['products']),
        }
        result['service_info'] = {
            'qty':   sum(p['quantity']    for c in services for p in c['products']),
            'total': sum(p['base_amount'] for c in services for p in c['products']),
        }

        # ── 5. Consolidated payments by method ────────────────────────────
        # Payments without 'id' are synthetic opening-float entries (total=0)
        # inserted by the parent for sessions without a cash method — skip them.
        method_env   = self.env['pos.payment.method']
        consolidated = {}
        for p in result.get('payments', []):
            mid = p.get('id')
            if not mid:
                continue
            if mid not in consolidated:
                consolidated[mid] = {
                    'name':  method_env.browse(mid).name,
                    'total': 0.0,
                }
            consolidated[mid]['total'] += p.get('total', 0.0)
        result['payments_consolidated'] = sorted(
            consolidated.values(), key=lambda x: x['name']
        )

        return result
