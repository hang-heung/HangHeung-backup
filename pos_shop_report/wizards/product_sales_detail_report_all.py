from odoo import models, fields
from datetime import datetime, time
import pytz
from collections import defaultdict
from odoo.exceptions import ValidationError
import xlsxwriter
import io
import base64


class ProductSaleAllShopReportWizard(models.TransientModel):
    _name = 'product.sale.all.shop.report.wizard'
    _description = 'POS Product All Store Report Wizard'

    from_date = fields.Date(string='From Date', required=True)
    to_date = fields.Date(string='To Date', required=True)
    file_data = fields.Binary('Excel File', readonly=True)
    file_name = fields.Char('File Name', readonly=True)

    def generate_report(self):
        tz = pytz.timezone(self.env.user.tz or 'UTC')
        start_utc = tz.localize(datetime.combine(self.from_date, time.min)).astimezone(pytz.UTC)
        end_utc = tz.localize(datetime.combine(self.to_date, time.max)).astimezone(pytz.UTC)

        orders = self.env['pos.order'].search([
            ('state', 'in', ['paid', 'invoiced', 'done']),
            ('date_order', '>=', start_utc.strftime('%Y-%m-%d %H:%M:%S')),
            ('date_order', '<=', end_utc.strftime('%Y-%m-%d %H:%M:%S')),
        ])
        if not orders:
            raise ValidationError('There are no orders for this date range')

        # Determine shops from the orders
        shops = orders.mapped('config_id').sorted('name')

        # --- Aggregate in ONE pass ---
        # Build order_id → shop_id map from the already-fetched orders recordset
        order_to_shop = {o.id: o.config_id.id for o in orders}

        # Fetch all lines in a single SQL read — no ORM lazy-loading
        line_vals = self.env['pos.order.line'].search_read(
            [('order_id', 'in', orders.ids)],
            ['product_id', 'order_id', 'qty', 'price_subtotal_incl', 'price_subtotal'],
        )

        if not line_vals:
            raise ValidationError('There are no order lines for this date range')

        # agg[product_id][shop_id] = [qty, gross, net]
        agg = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0.0]))
        product_ids_seen = set()
        for lv in line_vals:
            pid = lv['product_id'][0]
            shop_id = order_to_shop.get(lv['order_id'][0] if isinstance(lv['order_id'], (list, tuple)) else lv['order_id'])
            if not shop_id:
                continue
            product_ids_seen.add(pid)
            agg[pid][shop_id][0] += lv['qty']
            agg[pid][shop_id][1] += lv['price_subtotal_incl']
            agg[pid][shop_id][2] += lv['price_subtotal']

        # Fetch product meta — goods only (type == 'consu'), sorted by POS category then product code
        def _sort_key(p):
            cats = p.pos_categ_ids.sorted('sequence')
            return (
                cats[0].sequence if cats else 9999,
                cats[0].name if cats else '',
                p.default_code or '',
                p.display_name,
            )

        products = self.env['product.product'].browse(list(product_ids_seen)).filtered(
            lambda p: p.type in ('consu', 'product')
        ).sorted(key=_sort_key)

        if not products:
            raise ValidationError('There are no goods products in orders for this date range.')

        # --- Build Excel ---
        # Column layout:
        #   0 (A): 產品編號
        #   1 (B): 產品名稱
        #   2 (C): POS分類
        #   3+   : per-shop [qty, gross, net] × n shops
        #   last3: 總銷售數量, 總銷售總額, 總銷售淨額
        DATA_START = 3   # first shop column index

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet("Product Sales Detail Report (All Stores)")
        worksheet.set_column('A:A', 15)
        worksheet.set_column('B:B', 25)
        worksheet.set_column('C:C', 20)
        worksheet.set_column('D:ZZ', 12)

        fmt = {
            'shop_header':  workbook.add_format({'align': 'center', 'valign': 'vcenter', 'border': 1, 'bold': True}),
            'col_header':   workbook.add_format({'align': 'center', 'valign': 'vcenter', 'border': 1}),
            'cell':         workbook.add_format({'border': 1, 'align': 'right'}),
            'bold':         workbook.add_format({'bold': True, 'border': 1}),
            'label':        workbook.add_format({'border': 1, 'align': 'left'}),
            'title':        workbook.add_format({'bold': True, 'font_size': 12}),
            'title_header': workbook.add_format({'align': 'left', 'valign': 'vcenter', 'border': 1, 'bold': True}),
        }

        company_name = self.env.company.name
        worksheet.merge_range("A1:C1", company_name, fmt['title'])
        worksheet.merge_range("A2:C2", "產品銷售明細報告 (全線)", fmt['title_header'])
        worksheet.write("A3", "日期區間:", fmt['title'])
        worksheet.write("B3", f"{self.from_date.strftime('%Y-%m-%d')} 至 {self.to_date.strftime('%Y-%m-%d')}")

        date_label = f"{self.from_date.strftime('%Y-%m-%d')} 至 {self.to_date.strftime('%Y-%m-%d')}"

        # Rows 4–5: date / shop name headers — blank span for the 3 label columns, then 3 cols per shop
        row = 4
        col = DATA_START
        worksheet.merge_range(row,     0, row,     DATA_START - 1, '', fmt['shop_header'])
        worksheet.merge_range(row + 1, 0, row + 1, DATA_START - 1, '', fmt['shop_header'])
        for shop in shops:
            worksheet.merge_range(row,     col, row,     col + 2, date_label,  fmt['shop_header'])
            worksheet.merge_range(row + 1, col, row + 1, col + 2, shop.name,   fmt['shop_header'])
            col += 3
        worksheet.merge_range(row,     col, row,     col + 2, date_label,   fmt['shop_header'])
        worksheet.merge_range(row + 1, col, row + 1, col + 2, "All Stores", fmt['shop_header'])

        # Row 6: column sub-headers
        row = 6
        worksheet.write(row, 0, "產品編號",  fmt['col_header'])
        worksheet.write(row, 1, "產品名稱",  fmt['col_header'])
        worksheet.write(row, 2, "POS分類",   fmt['col_header'])
        col = DATA_START
        for _ in shops:
            worksheet.write(row, col,     "銷售數量", fmt['col_header']); col += 1
            worksheet.write(row, col,     "銷售總額", fmt['col_header']); col += 1
            worksheet.write(row, col,     "銷售淨額", fmt['col_header']); col += 1
        worksheet.write(row, col,     "總銷售數量", fmt['col_header'])
        worksheet.write(row, col + 1, "總銷售總額", fmt['col_header'])
        worksheet.write(row, col + 2, "總銷售淨額", fmt['col_header'])

        # Totals accumulators per shop
        tot_qty   = defaultdict(float)
        tot_gross = defaultdict(float)
        tot_net   = defaultdict(float)

        row = 7
        for product in products:
            pid = product.id
            # Resolve primary POS category name (lowest sequence, or blank)
            cats = product.pos_categ_ids.sorted('sequence')
            cat_name = cats[0].name if cats else ''

            worksheet.write(row, 0, product.default_code or '', fmt['label'])
            worksheet.write(row, 1, product.display_name,       fmt['label'])
            worksheet.write(row, 2, cat_name,                   fmt['label'])
            col = DATA_START

            p_qty = p_gross = p_net = 0.0
            for shop in shops:
                vals = agg[pid].get(shop.id, [0.0, 0.0, 0.0])
                worksheet.write(row, col,     vals[0], fmt['cell']); col += 1
                worksheet.write(row, col,     vals[1], fmt['cell']); col += 1
                worksheet.write(row, col,     vals[2], fmt['cell']); col += 1
                p_qty   += vals[0]
                p_gross += vals[1]
                p_net   += vals[2]
                tot_qty[shop.id]   += vals[0]
                tot_gross[shop.id] += vals[1]
                tot_net[shop.id]   += vals[2]

            worksheet.write(row, col,     p_qty,   fmt['cell'])
            worksheet.write(row, col + 1, p_gross, fmt['cell'])
            worksheet.write(row, col + 2, p_net,   fmt['cell'])
            row += 1

        # Totals row
        worksheet.merge_range(row, 0, row, DATA_START - 1, "總數", fmt['bold'])
        col = DATA_START
        grand_qty = grand_gross = grand_net = 0.0
        for shop in shops:
            worksheet.write(row, col,     tot_qty[shop.id],   fmt['bold']); col += 1
            worksheet.write(row, col,     tot_gross[shop.id], fmt['bold']); col += 1
            worksheet.write(row, col,     tot_net[shop.id],   fmt['bold']); col += 1
            grand_qty   += tot_qty[shop.id]
            grand_gross += tot_gross[shop.id]
            grand_net   += tot_net[shop.id]
        worksheet.write(row, col,     grand_qty,   fmt['bold'])
        worksheet.write(row, col + 1, grand_gross, fmt['bold'])
        worksheet.write(row, col + 2, grand_net,   fmt['bold'])

        workbook.close()
        output.seek(0)
        excel_data = output.read()
        self.write({
            'file_data': base64.b64encode(excel_data),
            'file_name': f"產品銷售明細報告 (全線) {self.from_date.strftime('%Y-%m-%d')} 至 {self.to_date.strftime('%Y-%m-%d')}.xlsx",
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f"/web/content/?model={self._name}&id={self.id}&field=file_data&filename_field=file_name&download=true",
            'target': 'self',
        }
