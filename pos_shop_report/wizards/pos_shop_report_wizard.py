from collections import defaultdict
from odoo import models, fields,api
from datetime import time, timedelta, datetime
from odoo.exceptions import ValidationError
import pytz


class POSShopReportWizard(models.TransientModel):
    _name = 'pos.shop.report.wizard'
    _description = 'POS Shop Report Wizard'

    shop_id = fields.Many2one('pos.config', string='Shop', required=True)
    date_start = fields.Date(string='Start Date', required=True)
    date_end = fields.Date(string='End Date', required=True)

    report_lines = fields.Json(string='Report Lines', readonly=True)
    coupon_lines = fields.Json(string='Coupon Lines', readonly=True)
    payment_breakdown = fields.Json(string='Payment Breakdown', readonly=True)
    coupon_discount_total = fields.Float(string="Deducted Coupon", readonly=True)
    company_name = fields.Char(string="Company", compute="_compute_company_name")

    shop_address = fields.Char(string="Shop Address", compute="_compute_shop_contact")
    shop_phone = fields.Char(string="Shop Phone", compute="_compute_shop_contact")

    @api.depends('shop_id')
    def _compute_shop_contact(self):
        for wizard in self:
            warehouse = self.env['stock.warehouse'].search([('name', '=', wizard.shop_id.name)], limit=1)
            if warehouse and warehouse.partner_id:
                partner = warehouse.partner_id
                address_parts = [
                    partner.street or '',
                    partner.street2 or '',
                    partner.city or '',
                    partner.state_id.name if partner.state_id else '',
                    partner.zip or '',
                    partner.country_id.name if partner.country_id else ''
                ]
                wizard.shop_address = ', '.join([part for part in address_parts if part])
                wizard.shop_phone = partner.phone or ''
            else:
                wizard.shop_address = ''
                wizard.shop_phone = ''

    @api.depends('shop_id')
    def _compute_company_name(self):
        for wizard in self:
            wizard.company_name = wizard.shop_id.company_id.name if wizard.shop_id.company_id else self.env.company.name

    @api.onchange('date_end')
    def _check_date_range(self):
        for record in self:
            if record.date_start and record.date_end and record.date_end < record.date_start:
                raise ValidationError("End Date cannot be earlier than Start Date.")

    def generate_report(self):
        self.ensure_one()
        self.report_lines = self._compute_report_lines()
        self.coupon_lines = self._compute_coupon_lines()
        self.payment_breakdown = self._compute_payment_breakdown()
        self.coupon_discount_total = self._compute_coupon_discount()
        return self.env.ref('pos_shop_report.action_pos_shop_report').report_action(self)

    def _compute_report_lines(self):
        self.ensure_one()
        PosLine = self.env['pos.order.line']
        StockMove = self.env['stock.move']
        StockScrap = self.env['stock.scrap']
        StockQuant = self.env['stock.quant']

        warehouse = self.shop_id.picking_type_id.warehouse_id
        if not warehouse:
            warehouse = self.env['stock.warehouse'].search(
                [('name', '=', self.shop_id.name)], limit=1)

        # Compute the shop's internal locations early so both the
        # POS-driven and stock-driven candidate sets can use them.
        shop_internal_location_ids = []
        if warehouse and warehouse.view_location_id:
            shop_internal_location_ids = self.env['stock.location'].search([
                ('id', 'child_of', warehouse.view_location_id.id),
                ('usage', '=', 'internal'),
            ]).ids

        lines = PosLine.search([
            ('order_id.config_id', '=', self.shop_id.id),
            ('order_id.date_order', '>=', self.date_start),
            ('order_id.date_order', '<=', self.date_end),
        ])

        result = {}
        for line in lines.filtered(
            lambda l: l.price_subtotal_incl >= 0
            and not l.product_id.product_tmpl_id.is_coupon
        ):
            product = line.product_id
            key = product.id
            if key not in result:
                result[key] = {
                    '_product_id': product.id,
                    'sku': product.default_code or '',
                    'name': product.name or '',
                    'previous_stock': 0,
                    'stock_in': 0,
                    'scrap_qty': 0,
                    'sales_qty': 0,
                    'sales_refund_qty': 0,
                    'total_qty_today': 0,
                    'sales_amount': 0,
                    'discount_amount': 0,
                    'final_amount': 0,
                }

            res = result[key]
            qty = line.qty
            price = line.price_unit
            discount = (price * qty) * (line.discount / 100)

            if qty > 0:
                res['sales_qty'] += qty
            else:
                res['sales_refund_qty'] += abs(qty)

            res['sales_amount'] += qty * price
            res['discount_amount'] += abs(discount)

        prev_date = self.date_start - timedelta(days=1)

        # HH-CUSTOM: also include any product touched by the shop in the
        # period via stock_in / scrap / current quants, so the report
        # shows every item where ANY of {previous_stock, stock_in,
        # scrap_qty, sales_qty, sales_refund_qty} ends up non-zero.
        # An empty stub row is created for each candidate; metrics get
        # filled in below; rows still all-zero are dropped at the end.
        if shop_internal_location_ids:
            extra_pids = set()
            for grp in StockQuant.read_group(
                domain=[
                    ('location_id', 'in', shop_internal_location_ids),
                    ('quantity', '!=', 0),
                ],
                fields=['product_id'],
                groupby=['product_id'],
            ):
                extra_pids.add(grp['product_id'][0])
            for grp in StockMove.read_group(
                domain=[
                    ('date', '>=', self.date_start),
                    ('date', '<=', self.date_end),
                    ('state', '=', 'done'),
                    ('location_dest_id', 'in', shop_internal_location_ids),
                    ('location_id', 'not in', shop_internal_location_ids),
                ],
                fields=['product_id'],
                groupby=['product_id'],
            ):
                extra_pids.add(grp['product_id'][0])
            for grp in StockScrap.read_group(
                domain=[
                    ('date_done', '>=', self.date_start),
                    ('date_done', '<=', self.date_end),
                    ('state', '=', 'done'),
                    ('location_id', 'in', shop_internal_location_ids),
                ],
                fields=['product_id'],
                groupby=['product_id'],
            ):
                extra_pids.add(grp['product_id'][0])
            extra_pids -= set(result.keys())
            for p in self.env['product.product'].browse(list(extra_pids)):
                result[p.id] = {
                    '_product_id': p.id,
                    'sku': p.default_code or '',
                    'name': p.name or '',
                    'previous_stock': 0,
                    'stock_in': 0,
                    'scrap_qty': 0,
                    'sales_qty': 0,
                    'sales_refund_qty': 0,
                    'total_qty_today': 0,
                    'sales_amount': 0,
                    'discount_amount': 0,
                    'final_amount': 0,
                }

        if not result:
            raise ValidationError("No record Found.")

        product_ids = list(result.keys())
        products = self.env['product.product'].browse(product_ids)

        # previous_stock: qty on hand at end of day before date_start, scoped to the shop's warehouse
        prev_stock_by_id = {pid: 0 for pid in product_ids}
        if warehouse:
            for p in products.with_context(to_date=prev_date, warehouse_id=warehouse.id):
                prev_stock_by_id[p.id] = p.qty_available

        # stock_in: stock.move arriving INTO the shop's warehouse from outside the shop
        stock_in_by_id = defaultdict(float)
        scrap_by_id = defaultdict(float)
        if shop_internal_location_ids:
            for grp in StockMove.read_group(
                domain=[
                    ('product_id', 'in', product_ids),
                    ('date', '>=', self.date_start),
                    ('date', '<=', self.date_end),
                    ('state', '=', 'done'),
                    ('location_dest_id', 'in', shop_internal_location_ids),
                    ('location_id', 'not in', shop_internal_location_ids),
                ],
                fields=['product_id', 'product_uom_qty:sum'],
                groupby=['product_id'],
            ):
                stock_in_by_id[grp['product_id'][0]] = grp['product_uom_qty']

            # scrap_qty: stock.scrap whose source is in the shop's warehouse
            for grp in StockScrap.read_group(
                domain=[
                    ('product_id', 'in', product_ids),
                    ('date_done', '>=', self.date_start),
                    ('date_done', '<=', self.date_end),
                    ('state', '=', 'done'),
                    ('location_id', 'in', shop_internal_location_ids),
                ],
                fields=['product_id', 'scrap_qty:sum'],
                groupby=['product_id'],
            ):
                scrap_by_id[grp['product_id'][0]] = grp['scrap_qty']

        for pid, data in result.items():
            data['previous_stock'] = prev_stock_by_id.get(pid, 0)
            data['stock_in'] = stock_in_by_id.get(pid, 0)
            data['scrap_qty'] = scrap_by_id.get(pid, 0)
            data['total_qty_today'] = (
                data['previous_stock']
                + data['stock_in']
                - data['scrap_qty']
                - data['sales_qty']
                + data['sales_refund_qty']
            )
            data['final_amount'] = data['sales_amount'] - data['discount_amount']

        # HH-CUSTOM: drop rows where every quantity metric is zero. A row
        # only deserves a line on the report if at least one of
        # 前一天上傳數 / 進貨數總和 / 當天棄貨數 / 銷售數 / 銷售退貨數
        # is non-zero.
        result = {
            pid: d for pid, d in result.items()
            if d['previous_stock'] or d['stock_in'] or d['scrap_qty']
            or d['sales_qty'] or d['sales_refund_qty']
        }

        # Sort by POS category name then SKU (default_code) ascending.
        # Products without any pos_categ_ids fall to the end via 'zzz' sentinel.
        cat_by_pid = {}
        for prod in products:
            cat_names = prod.product_tmpl_id.pos_categ_ids.mapped('name')
            cat_by_pid[prod.id] = sorted(cat_names)[0] if cat_names else 'zzz'

        result_list = list(result.values())
        result_list.sort(key=lambda r: (cat_by_pid.get(r['_product_id'], 'zzz'), r['sku'] or ''))
        for r in result_list:
            r.pop('_product_id', None)
        return result_list

    def _compute_coupon_lines(self):
        self.ensure_one()
        LoyaltyCard = self.env['loyalty.card']
        PosLine = self.env['pos.order.line']

        user_tz = self.env.user.tz or 'UTC'
        tz = pytz.timezone(user_tz)
        start_local = tz.localize(datetime.combine(self.date_start, time.min))
        end_local = tz.localize(datetime.combine(self.date_end, time.max))
        start_utc = start_local.astimezone(pytz.UTC)
        end_utc = end_local.astimezone(pytz.UTC)

        coupon_products = self.env['product.product'].search([
            ('product_tmpl_id.is_coupon', '=', True),
            ('product_tmpl_id.loyalty_program_id', '!=', False),
        ])

        coupon_lines = []
        for product in coupon_products:
            program = product.product_tmpl_id.loyalty_program_id

            allocated_not_activated = LoyaltyCard.search_count([
                ('program_id', '=', program.id),
                ('store_id', '=', self.shop_id.id),
                ('status', '=', 'not_activated'),
            ])

            redeemed_lines = PosLine.search([
                ('order_id.config_id', '=', self.shop_id.id),
                ('order_id.date_order', '>=', start_utc),
                ('order_id.date_order', '<=', end_utc),
                ('is_reward_line', '=', True),
                ('coupon_id.program_id', '=', program.id),
            ])
            redeemed_count = len(redeemed_lines.mapped('coupon_id'))
            redemption_sales = abs(sum(redeemed_lines.mapped('price_subtotal_incl')))

            if allocated_not_activated == 0 and redeemed_count == 0:
                continue

            coupon_lines.append({
                'program_name': program.name or '',
                'sku': product.default_code or '',
                'name': product.name or '',
                'face_value': product.list_price or 0.0,
                'allocated_not_activated': allocated_not_activated,
                'redeemed_in_period': redeemed_count,
                'redemption_sales': redemption_sales,
            })

        coupon_lines.sort(key=lambda d: (d['program_name'], d['sku']))
        return coupon_lines
    

    def _compute_payment_breakdown(self):
        Payment = self.env['pos.payment']
        user_tz = self.env.user.tz or 'UTC'
        tz = pytz.timezone(user_tz)

        start_local = tz.localize(datetime.combine(self.date_start, time.min))
        end_local = tz.localize(datetime.combine(self.date_end, time.max))

        start_utc = start_local.astimezone(pytz.UTC)
        end_utc = end_local.astimezone(pytz.UTC)

        orders = self.env['pos.order'].search([
            ('config_id', '=', self.shop_id.id),
            ('date_order', '>=', start_utc),
            ('date_order', '<=', end_utc),
            ('state', 'in', ['paid', 'done', 'invoiced']),
        ])
        payments = Payment.search([('pos_order_id', 'in', orders.ids)])
        
        breakdown = {}
        for payment in payments:
            name = payment.payment_method_id.name
            breakdown[name] = breakdown.get(name, 0.0) + payment.amount
        return breakdown

    def _compute_coupon_discount(self):
        PosLine = self.env['pos.order.line']
        lines = PosLine.search([
            ('order_id.config_id', '=', self.shop_id.id),
            ('order_id.date_order', '>=', self.date_start),
            ('order_id.date_order', '<=', self.date_end),
        ])
        discounted_lines = lines.filtered(lambda l: l.price_subtotal_incl < 0 and l.qty >= 0)

        return abs(sum(discounted_lines.mapped('price_subtotal_incl')))

