import io
import base64
import pytz
import xlsxwriter
from datetime import timedelta, datetime, time
from collections import defaultdict
from odoo import models, fields
from odoo.exceptions import ValidationError


class DailyProductSalesInventoryReport(models.TransientModel):
    _name = 'daily.product.sales.inventory.report'
    _description = 'POS Daily Product Sales and Inventory Report'

    shop_id = fields.Many2one('pos.config', string='Shop', required=True)
    date_start = fields.Date(string='Start Date', required=True)
    date_end = fields.Date(string='End Date', required=True)

    def _get_shop_info(self):
        warehouse = self.shop_id.picking_type_id.warehouse_id
        if not warehouse:
            warehouse = self.env['stock.warehouse'].search(
                [('name', '=', self.shop_id.name)], limit=1)
        if not warehouse:
            return None, []
        loc_ids = self.env['stock.location'].search([
            ('id', 'child_of', warehouse.view_location_id.id),
            ('usage', '=', 'internal'),
        ]).ids
        return warehouse, loc_ids

    def _compute_report_lines(self):
        self.ensure_one()
        company = self.env.company
        warehouse, shop_location_ids = self._get_shop_info()
        if not shop_location_ids:
            raise ValidationError("Cannot determine warehouse locations for this shop.")

        user_tz = pytz.timezone(self.env.user.tz or 'UTC')
        prev_end_utc = user_tz.localize(
            datetime.combine(self.date_start - timedelta(days=1), time.max)
        ).astimezone(pytz.UTC).strftime('%Y-%m-%d %H:%M:%S')
        period_start_utc = user_tz.localize(
            datetime.combine(self.date_start, time.min)
        ).astimezone(pytz.UTC).strftime('%Y-%m-%d %H:%M:%S')
        period_end_utc = user_tz.localize(
            datetime.combine(self.date_end, time.max)
        ).astimezone(pytz.UTC).strftime('%Y-%m-%d %H:%M:%S')

        StockMove = self.env['stock.move']

        # Previous stock: all moves into/out of shop up to end of previous day
        prev_in = defaultdict(float)
        prev_out = defaultdict(float)
        for grp in StockMove.read_group(
            domain=[('state','=','done'),('date','<=',prev_end_utc),
                    ('company_id','=',company.id),('location_dest_id','in',shop_location_ids)],
            fields=['product_id','product_uom_qty:sum'], groupby=['product_id'],
        ):
            prev_in[grp['product_id'][0]] += grp['product_uom_qty']
        for grp in StockMove.read_group(
            domain=[('state','=','done'),('date','<=',prev_end_utc),
                    ('company_id','=',company.id),('location_id','in',shop_location_ids)],
            fields=['product_id','product_uom_qty:sum'], groupby=['product_id'],
        ):
            prev_out[grp['product_id'][0]] += grp['product_uom_qty']
        prev_stock_by_id = defaultdict(float)
        for pid in set(list(prev_in.keys()) + list(prev_out.keys())):
            prev_stock_by_id[pid] = prev_in[pid] - prev_out[pid]

        # 進貨數: direct supplier/vendor receipts INTO shop only
        stock_in_by_id = defaultdict(float)
        for grp in StockMove.read_group(
            domain=[
                ('state','=','done'),
                ('date','>=',period_start_utc),('date','<=',period_end_utc),
                ('company_id','=',company.id),
                ('location_dest_id','in',shop_location_ids),
                ('location_id.usage','=','supplier'),
            ],
            fields=['product_id','product_uom_qty:sum'], groupby=['product_id'],
        ):
            stock_in_by_id[grp['product_id'][0]] += grp['product_uom_qty']

        # 調撥數: net internal/transit transfers (+ in, - out)
        transfer_by_id = defaultdict(float)
        # Transfers IN: from internal/transit locations into shop
        for grp in StockMove.read_group(
            domain=[
                ('state','=','done'),
                ('date','>=',period_start_utc),('date','<=',period_end_utc),
                ('company_id','=',company.id),
                ('location_dest_id','in',shop_location_ids),
                ('location_id','not in',shop_location_ids),
                ('location_id.usage','in',['internal','transit']),
            ],
            fields=['product_id','product_uom_qty:sum'], groupby=['product_id'],
        ):
            transfer_by_id[grp['product_id'][0]] += grp['product_uom_qty']
        # Transfers OUT: from shop to internal/transit locations
        for grp in StockMove.read_group(
            domain=[
                ('state','=','done'),
                ('date','>=',period_start_utc),('date','<=',period_end_utc),
                ('company_id','=',company.id),
                ('location_id','in',shop_location_ids),
                ('location_dest_id','not in',shop_location_ids),
                ('location_dest_id.usage','in',['internal','transit']),
            ],
            fields=['product_id','product_uom_qty:sum'], groupby=['product_id'],
        ):
            transfer_by_id[grp['product_id'][0]] -= grp['product_uom_qty']

        # 棄貨數: scrap from shop
        scrap_by_id = defaultdict(float)
        for grp in self.env['stock.scrap'].read_group(
            domain=[
                ('state','=','done'),
                ('date_done','>=',period_start_utc),('date_done','<=',period_end_utc),
                ('company_id','=',company.id),
                ('location_id','in',shop_location_ids),
            ],
            fields=['product_id','scrap_qty:sum'], groupby=['product_id'],
        ):
            scrap_by_id[grp['product_id'][0]] = grp['scrap_qty']

        # 調整數: inventory adjustments (net)
        adjustment_by_id = defaultdict(float)
        for grp in StockMove.read_group(
            domain=[
                ('state','=','done'),
                ('date','>=',period_start_utc),('date','<=',period_end_utc),
                ('company_id','=',company.id),
                ('location_id.usage','=','inventory'),
                ('location_dest_id','in',shop_location_ids),
                ('scrapped','=',False),
            ],
            fields=['product_id','product_uom_qty:sum'], groupby=['product_id'],
        ):
            adjustment_by_id[grp['product_id'][0]] += grp['product_uom_qty']
        for grp in StockMove.read_group(
            domain=[
                ('state','=','done'),
                ('date','>=',period_start_utc),('date','<=',period_end_utc),
                ('company_id','=',company.id),
                ('location_id','in',shop_location_ids),
                ('location_dest_id.usage','=','inventory'),
                ('scrapped','=',False),
            ],
            fields=['product_id','product_uom_qty:sum'], groupby=['product_id'],
        ):
            adjustment_by_id[grp['product_id'][0]] -= grp['product_uom_qty']

        # POS sales lines
        lines = self.env['pos.order.line'].search([
            ('order_id.config_id','=',self.shop_id.id),
            ('order_id.state','in',['paid','done','invoiced']),
            ('order_id.date_order','>=',period_start_utc),
            ('order_id.date_order','<=',period_end_utc),
            ('order_id.company_id','=',company.id),
        ])

        # Seed from current stock.quant (products physically on shelf)
        quant_pids = set()
        for grp in self.env['stock.quant'].read_group(
            domain=[('location_id','in',shop_location_ids),('quantity','>',0)],
            fields=['product_id'], groupby=['product_id'],
        ):
            quant_pids.add(grp['product_id'][0])

        active_pids = quant_pids | set(
            list(prev_stock_by_id.keys()) +
            list(stock_in_by_id.keys()) +
            list(transfer_by_id.keys()) +
            list(scrap_by_id.keys()) +
            list(adjustment_by_id.keys()) +
            [l.product_id.id for l in lines]
        )

        # Keep only goods (storable + consumable), exclude services
        active_pids &= set(self.env['product.product'].search([
            ('id','in',list(active_pids)),
            ('type','in',['product','consu']),
        ]).ids)

        if not active_pids:
            raise ValidationError("No stock or activity found for this shop and date range.")

        products = self.env['product.product'].browse(list(active_pids))
        result = {}
        for product in products:
            pid = product.id
            result[pid] = {
                'product_id': pid,
                'sku': product.default_code or '',
                'name': product.name or '',
                'unit': product.uom_id.name,
                'price': product.lst_price,
                'previous_stock': prev_stock_by_id.get(pid, 0),
                'stock_in': stock_in_by_id.get(pid, 0),
                'transfer_qty': transfer_by_id.get(pid, 0),
                'scrap_qty': scrap_by_id.get(pid, 0),
                'adjustment_qty': adjustment_by_id.get(pid, 0),
                'sales_qty': 0,
                'sales_refund_qty': 0,
                'total_qty_today': 0,
                'sales_amount': 0,
                'discount_amount': 0,
                'final_amount': 0,
                'closing_stock': 0,
            }

        for line in lines:
            pid = line.product_id.id
            if pid not in result:
                continue
            res = result[pid]
            qty = line.qty
            price = line.price_unit
            discount = (price * qty) * (line.discount / 100)
            if qty > 0:
                res['sales_qty'] += qty
                res['sales_amount'] += qty * price
                res['discount_amount'] += discount
            else:
                res['sales_refund_qty'] += abs(qty)
                res['sales_amount'] -= abs(qty * price)
                res['discount_amount'] += discount

        for res in result.values():
            res['total_qty_today'] = res['sales_qty'] + res['sales_refund_qty']
            res['final_amount'] = res['sales_amount'] - res['discount_amount']
            res['closing_stock'] = (
                res['previous_stock']
                + res['stock_in']
                + res['transfer_qty']
                - res['sales_qty']
                + res['sales_refund_qty']
                - res['scrap_qty']
                + res['adjustment_qty']
            )

        # Show row if ANY field is non-zero:
        # 上存數 / 進貨數 / 調撥數 / 銷售數 / 退貨數 / 棄貨數 / 調整數 / 結存數
        result = {
            pid: d for pid, d in result.items()
            if d['previous_stock'] or d['stock_in'] or d['transfer_qty']
            or d['sales_qty'] or d['sales_refund_qty'] or d['scrap_qty']
            or d['adjustment_qty'] or d['closing_stock']
        }

        return list(result.values())

    def generate_xls_report(self):
        company = self.env.company
        self.ensure_one()
        report_lines = self._compute_report_lines()

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Daily Product Sales and Inventory Report')

        header_title = workbook.add_format({'bold': True, 'font_size': 14})
        header_label = workbook.add_format({'bold': True, 'font_size': 12})
        header_value = workbook.add_format({'font_size': 12})
        table_header = workbook.add_format({'bold': True, 'bg_color': '#CCCCCC', 'border': 1})
        normal_format = workbook.add_format({'border': 1})

        row = 0
        sheet.set_column('A:A', 25)
        sheet.set_column('B:B', 35)
        sheet.set_column('C:O', 10)

        sheet.write(row, 0, company.name, header_title); row += 2
        sheet.write(row, 0, "當天貨品銷售及庫存報表", header_label); row += 2
        sheet.write(row, 0, "日期:", header_label)
        sheet.write(row, 1, f"{self.date_start} ~ {self.date_end}", header_value); row += 1
        sheet.write(row, 0, "分店:", header_label)
        sheet.write(row, 1, self.shop_id.name or '', header_value); row += 2

        headers = [
            '產品編號', '產品名稱', '單位', '價錢',
            '上存', '進貨數', '調撥數', '銷售數', '退貨數', '棄貨數', '調整數', '結存數',
            '銷售金額', '折扣金額', '銷售淨額'
        ]
        for col, header in enumerate(headers):
            sheet.write(row, col, header, table_header)
        row += 1

        for line in report_lines:
            sheet.write(row, 0,  line.get('sku', ''),              normal_format)
            sheet.write(row, 1,  line.get('name', ''),             normal_format)
            sheet.write(row, 2,  line.get('unit', ''),             normal_format)
            sheet.write(row, 3,  line.get('price', 0.0),           normal_format)
            sheet.write(row, 4,  line.get('previous_stock', 0),    normal_format)
            sheet.write(row, 5,  line.get('stock_in', 0),          normal_format)
            sheet.write(row, 6,  line.get('transfer_qty', 0),      normal_format)
            sheet.write(row, 7,  line.get('sales_qty', 0),         normal_format)
            sheet.write(row, 8,  line.get('sales_refund_qty', 0),  normal_format)
            sheet.write(row, 9,  line.get('scrap_qty', 0),         normal_format)
            sheet.write(row, 10, line.get('adjustment_qty', 0),    normal_format)
            sheet.write(row, 11, line.get('closing_stock', 0),     normal_format)
            sheet.write(row, 12, line.get('sales_amount', 0.0),    normal_format)
            sheet.write(row, 13, line.get('discount_amount', 0.0), normal_format)
            sheet.write(row, 14, line.get('final_amount', 0.0),    normal_format)
            row += 1

        workbook.close()
        output.seek(0)

        filename = f"貨品銷售及庫存報表 {self.shop_id.name} {self.date_start.strftime('%Y-%m-%d')} 至 {self.date_end.strftime('%Y-%m-%d')}.xlsx"
        attachment = self.env['ir.attachment'].create({
            'name': filename, 'type': 'binary',
            'datas': base64.b64encode(output.read()),
            'res_model': self._name, 'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    def generate_pdf_report(self):
        return self.env.ref(
            'pos_shop_report.action_daily_product_sales_inventory_report_pdf'
        ).report_action(self)
