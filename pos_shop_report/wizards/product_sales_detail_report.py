from odoo import models, fields, _
import io
import base64
from odoo.tools.misc import xlsxwriter
from odoo.exceptions import ValidationError


class ProductSalesDetailReport(models.TransientModel):
    _name = 'product.sales.detail.report.wizard'
    _description = 'Product Sales Detail Report (Individual Store)'

    from_date = fields.Date('From Date', required=True)
    to_date = fields.Date('To Date', required=True)
    store_id = fields.Many2one('pos.config', string='Store', required=True)

    def action_generate_excel(self):
        company = self.env.company
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Product Sales Detail Report (Individual Store)')

        bold = workbook.add_format({'bold': True})
        header_format = workbook.add_format({'bold': True, 'align': 'center'})
        normal = workbook.add_format({'align': 'left'})

        sheet.set_column('A:A', 25)
        sheet.set_column('B:B', 35)
        sheet.set_column('C:C', 10)
        sheet.set_column('D:D', 10)
        sheet.set_column('E:E', 10)

        sheet.write(0, 0, company.name, bold)
        sheet.write(1, 0, "產品銷售明細報告(個別分店)")
        sheet.write(2, 0, "日期區間:")
        sheet.write(2, 1, f"{self.from_date} 至 {self.to_date}")
        sheet.write(3, 0, "分店:")
        sheet.write(3, 1, self.store_id.name)

        headers = ["產品編號", "產品名稱", "銷售數量", "銷售總額", "銷售淨額"]
        for col, h in enumerate(headers):
            sheet.write(5, col, h, header_format)

        row = 6

        orders = self.env['pos.order'].search([
            ('date_order', '>=', f"{self.from_date} 00:00:00"),
            ('date_order', '<=', f"{self.to_date} 23:59:59"),
            ('session_id.config_id', '=', self.store_id.id),
            ('state', 'in', ['paid', 'done', 'invoiced']),
            ('company_id', '=', company.id),
        ])
        pos_lines = orders.mapped('lines')

        if not pos_lines:
            raise ValidationError(_('There are no orders for this date range.'))

        for line in pos_lines:
            if not line.product_id.default_code:
                continue
            sheet.write(row, 0, line.product_id.default_code, normal)
            sheet.write(row, 1, line.product_id.display_name, normal)
            sheet.write(row, 2, line.qty, normal)
            sheet.write(row, 3, line.price_subtotal_incl, normal)
            sheet.write(row, 4, line.price_subtotal, normal)
            row += 1

        workbook.close()
        output.seek(0)

        filename = f"Product Sales Detail Report {self.store_id.name} {self.from_date} 至 {self.to_date}.xlsx"
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
