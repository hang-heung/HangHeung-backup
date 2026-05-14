import io
import base64
import xlsxwriter
from datetime import timedelta
from collections import defaultdict
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class DailyProductSalesInventoryReport(models.TransientModel):
    _name = 'daily.product.sales.inventory.report'
    _description = 'POS Daily Product Sales and Inventory Report'

    shop_id = fields.Many2one('pos.config', string='Shop', required=True)
    date_start = fields.Date(string='Start Date', required=True)
    date_end = fields.Date(string='End Date', required=True)

    def _compute_report_lines(self):
        self.ensure_one()
        company = self.env.company

        all_products = self.env['product.product'].search([
            ('type', 'in', ['product', 'consu', 'combo']),
            ('company_id', 'in', [False, company.id]),
        ])
        product_ids = all_products.ids

        prev_date = self.date_start - timedelta(days=1)
        prev_stock_by_id = {
            p.id: p.qty_available
            for p in all_products.with_context(to_date=prev_date)
        }

        StockMove = self.env['stock.move']
        stock_in_by_id = defaultdict(float)
        for grp in StockMove.read_group(
            domain=[
                ('product_id', 'in', product_ids),
                ('date', '>=', self.date_start),
                ('date', '<=', self.date_end),
                ('state', '=', 'done'),
                ('company_id', '=', company.id),
            ],
            fields=['product_id', 'product_uom_qty:sum'],
            groupby=['product_id'],
        ):
            stock_in_by_id[grp['product_id'][0]] = grp['product_uom_qty']

        StockScrap = self.env['stock.scrap']
        scrap_by_id = defaultdict(float)
        for grp in StockScrap.read_group(
            domain=[
                ('product_id', 'in', product_ids),
                ('date_done', '>=', self.date_start),
                ('date_done', '<=', self.date_end),
                ('state', '=', 'done'),
                ('company_id', '=', company.id),
            ],
            fields=['product_id', 'scrap_qty:sum'],
            groupby=['product_id'],
        ):
            scrap_by_id[grp['product_id'][0]] = grp['scrap_qty']

        adjustment_location = self.env['stock.location'].search([
            ('complete_name', '=', 'Virtual Locations/Inventory adjustment'),
            ('company_id', '=', company.id),
        ], limit=1)

        adjustment_by_id = defaultdict(float)
        if adjustment_location:
            for grp in self.env['stock.quant'].read_group(
                domain=[
                    ('product_id', 'in', product_ids),
                    ('location_id', '=', adjustment_location.id),
                    ('company_id', '=', company.id),
                ],
                fields=['product_id', 'quantity:sum'],
                groupby=['product_id'],
            ):
                adjustment_by_id[grp['product_id'][0]] = grp['quantity']

        PosLine = self.env['pos.order.line']
        lines = PosLine.search([
            ('order_id.config_id', '=', self.shop_id.id),
            ('order_id.date_order', '>=', self.date_start),
            ('order_id.date_order', '<=', self.date_end),
            ('order_id.company_id', '=', company.id),
        ])

        result = {}
        for product in all_products:
            result[product.id] = {
                'product_id': product.id,
                'sku': product.default_code or '',
                'name': product.name or '',
                'unit': product.uom_id.name,
                'price': product.lst_price,
                'previous_stock': prev_stock_by_id.get(product.id, 0),
                'stock_in': stock_in_by_id.get(product.id, 0),
                'scrap_qty': scrap_by_id.get(product.id, 0),
                'adjustment_qty': adjustment_by_id.get(product.id, 0),
                'sales_qty': 0,
                'sales_refund_qty': 0,
                'total_qty_today': 0,
                'sales_amount': 0,
                'discount_amount': 0,
                'final_amount': 0,
                'closing_stock': 0,
            }

        for line in lines:
            product = line.product_id
            key = product.id

            if key not in result:
                result[key] = {
                    'product_id': product.id,
                    'sku': product.default_code or '',
                    'name': product.name or '',
                    'unit': product.uom_id.name,
                    'price': product.lst_price,
                    'previous_stock': 0,
                    'stock_in': stock_in_by_id.get(key, 0),
                    'scrap_qty': scrap_by_id.get(key, 0),
                    'adjustment_qty': adjustment_by_id.get(key, 0),
                    'sales_qty': 0,
                    'sales_refund_qty': 0,
                    'total_qty_today': 0,
                    'sales_amount': 0,
                    'discount_amount': 0,
                    'final_amount': 0,
                    'closing_stock': 0,
                }

            res = result[key]
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
                - res['sales_qty']
                + res['sales_refund_qty']
                - res['scrap_qty']
                + res['adjustment_qty']
            )

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
        sheet.set_column('C:N', 10)

        sheet.write(row, 0, company.name, header_title)
        row += 2

        sheet.write(row, 0, "當天貨品銷售及庫存報表", header_label)
        row += 2

        sheet.write(row, 0, "日期:", header_label)
        sheet.write(row, 1, f"{self.date_start} ~ {self.date_end}", header_value)
        row += 1

        sheet.write(row, 0, "分店:", header_label)
        sheet.write(row, 1, self.shop_id.name or '', header_value)
        row += 2

        headers = ['產品編號', '產品名稱', '單位', '價錢', '上存', '進貨數', '銷售數', '退貨數', '棄貨數', '調整數', '結存數', '銷售金額', '折扣金額', '銷售淨額']
        for col, header in enumerate(headers):
            sheet.write(row, col, header, table_header)
        row += 1

        for line in report_lines:
            # HH-CUSTOM: skip the product row when 上存 / 進貨 / 銷售 /
            # 退貨 / 調整 are all zero -- no movement to report.
            if not any((
                line.get('previous_stock') or 0,
                line.get('stock_in') or 0,
                line.get('sales_qty') or 0,
                line.get('sales_refund_qty') or 0,
                line.get('adjustment_qty') or 0,
            )):
                continue
            sheet.write(row, 0, line.get('sku', ''), normal_format)
            sheet.write(row, 1, line.get('name', ''), normal_format)
            sheet.write(row, 2, line.get('unit', ''), normal_format)
            sheet.write(row, 3, line.get('price', 0.0), normal_format)
            sheet.write(row, 4, line.get('previous_stock', 0), normal_format)
            sheet.write(row, 5, line.get('stock_in', 0), normal_format)
            sheet.write(row, 6, line.get('sales_qty', 0), normal_format)
            sheet.write(row, 7, line.get('sales_refund_qty', 0), normal_format)
            sheet.write(row, 8, line.get('scrap_qty', 0), normal_format)
            sheet.write(row, 9, line.get('adjustment_qty', 0), normal_format)
            sheet.write(row, 10, line.get('closing_stock', 0), normal_format)
            sheet.write(row, 11, line.get('sales_amount', 0.0), normal_format)
            sheet.write(row, 12, line.get('discount_amount', 0.0), normal_format)
            sheet.write(row, 13, line.get('final_amount', 0.0), normal_format)
            row += 1

        row += 2

        workbook.close()
        output.seek(0)

        filename = f"Daily Product Sales and Inventory Report {self.shop_id.name}.xlsx"
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(output.read()),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }
