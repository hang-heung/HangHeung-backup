from odoo import models, fields, api
from datetime import datetime, time
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
        # Prepare Excel
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet("Product Sales Detail Report (All Stores)")
        worksheet.set_column('A:A', 15)
        worksheet.set_column('B:B', 25)
        worksheet.set_column("C:Z", 10)  # Set default column width

        # Define all formats in a dictionary for easy reuse
        formats = {
            'shop_header': workbook.add_format({'align': 'center', 'valign': 'vcenter', 'border': 1}),
            'cell': workbook.add_format({'border': 1, 'align': 'center'}),
            'bold': workbook.add_format({'bold': True, 'border': 1}),
            'left_border': workbook.add_format({'align': 'center', 'valign': 'vcenter', 'left': 1}),
            'right_border': workbook.add_format({'align': 'center', 'valign': 'vcenter', 'right': 1}),
            'title_header': workbook.add_format({'align': 'left', 'valign': 'vcenter', 'border': 1, 'bold': True}),
            'title_value': workbook.add_format({'align': 'left', 'valign': 'vcenter', 'border': 1}),
            'title': workbook.add_format({'bold': True, 'font_size': 12}),
            'date_format': workbook.add_format({'num_format': 'yyyy-mm-dd', 'border': 1}),
            'no_border': workbook.add_format({'align': 'center', 'valign': 'vcenter', 'border': 0}),
        }

        # Title
        company_name = self.env.company.name
        worksheet.merge_range("A1:B1", company_name, formats['title'])
        worksheet.merge_range("A2:B2", "產品銷售明細報告 (全線)", formats['title_header'])
        worksheet.write("A3", "日期區間:", formats['title'])
        worksheet.write("C3", f"{self.from_date.strftime('%Y-%m-%d')} 至 {self.to_date.strftime('%Y-%m-%d')}")

        start_dt = datetime.combine(self.from_date, time.min)
        end_dt = datetime.combine(self.to_date, time.max)
        orders = self.env['pos.order'].search([
            ('state', 'in', ['paid', 'invoiced', 'done']),
            ('date_order', '>=', start_dt), ('date_order', '<=', end_dt)
        ])
        if not orders:
            raise ValidationError('There are no orders for this date range')

        shops = orders.mapped('session_id.config_id')

        # Column headers (shop data)
        row = 4
        col = 0
        worksheet.merge_range(row, col, row, col + 1, '', formats['shop_header'])
        worksheet.merge_range(row + 1, col, row + 1, col + 1, '', formats['shop_header'])
        col += 2

        # Shop headers (Date and Shop Name)
        for shop in shops:
            worksheet.merge_range(row, col, row, col + 2, f"{self.from_date.strftime('%Y-%m-%d')} 至 {self.to_date.strftime('%Y-%m-%d')}", formats['shop_header'])
            worksheet.merge_range(row + 1, col, row + 1, col + 2, shop.name, formats['shop_header'])
            col += 3

        # Merge for the totals header
        worksheet.merge_range(row, col, row, col + 2, "", formats['shop_header'])
        worksheet.merge_range(row + 1, col, row + 1, col + 2, "", formats['shop_header'])

        # Column Titles (Row 7)
        row = 6
        worksheet.write(row, 0, "產品編號", formats['cell'])
        worksheet.write(row, 1, "產品名稱", formats['cell'])

        col = 2
        for _ in shops:
            worksheet.write(row, col, "銷售數量", formats['cell']); col += 1
            worksheet.write(row, col, "銷售總額", formats['cell']); col += 1
            worksheet.write(row, col, "銷售淨額", formats['cell']); col += 1

        worksheet.write(row, col, "總銷售數量", formats['cell'])
        worksheet.write(row, col + 1, "總銷售總額", formats['cell'])
        worksheet.write(row, col + 2, "總銷售淨額", formats['cell'])

        # Process order lines for each product
        order_lines = orders.mapped('lines')
        overall_qty_per_shop = {shop: 0.0 for shop in shops}
        overall_gross_per_shop = {shop: 0.0 for shop in shops}
        overall_net_per_shop = {shop: 0.0 for shop in shops}

        row += 1
        for product in order_lines.mapped('product_id'):
            if not product.default_code:
                continue
            col = 0
            worksheet.write(row, col, product.default_code, formats['left_border'])
            worksheet.write(row, col + 1, product.display_name, formats['right_border'])
            col += 2

            total_qty = total_gross = total_net = 0.0

            for shop in shops:
                shop_lines = order_lines.filtered(lambda l: l.order_id.session_id.config_id == shop and l.product_id == product)

                qty = sum(shop_lines.mapped('qty'))
                gross = sum(l.price_unit * l.qty for l in shop_lines)
                net = sum(shop_lines.mapped('price_subtotal'))

                worksheet.write(row, col, qty, formats['left_border']); col += 1
                worksheet.write(row, col, gross, formats['no_border']); col += 1
                worksheet.write(row, col, net, formats['right_border']); col += 1

                total_qty += qty
                total_gross += gross
                total_net += net

                overall_qty_per_shop[shop] += qty
                overall_gross_per_shop[shop] += gross
                overall_net_per_shop[shop] += net

            worksheet.write(row, col, total_qty, formats['left_border'])
            worksheet.write(row, col + 1, total_gross, formats['no_border'])
            worksheet.write(row, col + 2, total_net, formats['right_border'])

            row += 1

        # Write overall totals for each shop
        col = 0
        worksheet.merge_range(row, col, row, col + 1, "總數", formats['bold'])

        col = 2
        for shop in shops:
            worksheet.write(row, col, overall_qty_per_shop[shop], formats['bold'])
            worksheet.write(row, col + 1, overall_gross_per_shop[shop], formats['bold'])
            worksheet.write(row, col + 2, overall_net_per_shop[shop], formats['bold'])
            col += 3

        # Write grand totals
        grand_total_qty = sum(overall_qty_per_shop.values())
        grand_total_gross = sum(overall_gross_per_shop.values())
        grand_total_net = sum(overall_net_per_shop.values())

        worksheet.write(row, col, grand_total_qty, formats['bold'])
        worksheet.write(row, col + 1, grand_total_gross, formats['bold'])
        worksheet.write(row, col + 2, grand_total_net, formats['bold'])

        # Close and save the workbook
        workbook.close()
        output.seek(0)
        excel_data = output.read()
        self.write({
            'file_data': base64.b64encode(excel_data),
            'file_name': f"Product Sales Detail Report ({self.from_date.strftime('%Y-%m-%d')} 至 {self.to_date.strftime('%Y-%m-%d')}).xlsx",
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f"/web/content/?model={self._name}&id={self.id}&field=file_data&filename_field=file_name&download=true",
            'target': 'self',
        }
