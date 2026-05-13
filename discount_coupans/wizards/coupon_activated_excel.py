from datetime import timedelta

from odoo import models, fields, api
import base64
import io
import xlsxwriter


class CouponActivatedExcelWizard(models.TransientModel):
    _name = 'coupon.activated.excel.wizard'
    _description = 'Activated Coupon Excel Wizard'

    from_date = fields.Date('From Date')
    to_date = fields.Date('To Date')
    file_data = fields.Binary('Excel File', readonly=True)
    file_name = fields.Char('File Name', readonly=True)

    def action_generate_excel(self):
        domain = [
            ('status', '=', 'activated'),
            ('program_id.program_type', '=', 'coupons')
        ]

        if self.from_date:
            domain.append(('date_activation', '>=', self.from_date))
        if self.to_date:
            # date_activation is a Datetime; '<= to_date' (Date cast to
            # midnight) drops every activation later that same day. Use
            # exclusive next-day upper bound.
            domain.append(('date_activation', '<', self.to_date + timedelta(days=1)))

        coupons = self.env['loyalty.card'].search(domain)

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Activated Coupons')

        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#D7E4BC',
            'align': 'center',
            'valign': 'vcenter'
        })
        cell_format = workbook.add_format({'text_wrap': True, 'valign': 'top'})

        headers = ['Program Name', 'Code', 'Prefix', 'Store', 'Status', 'Activation Date']

        sheet.set_column(0, 0, 30, cell_format)
        sheet.set_column(1, 1, 20, cell_format)
        sheet.set_column(2, 2, 15, cell_format)
        sheet.set_column(3, 3, 30, cell_format)
        sheet.set_column(4, 4, 20, cell_format)
        sheet.set_column(5, 5, 25, cell_format)

        
        for col, head in enumerate(headers):
            sheet.write(0, col, head, header_format)

       
        row = 1
        for coupon in coupons:
            sheet.write(row, 0, coupon.program_id.name or '', cell_format)
            sheet.write(row, 1, coupon.code or '', cell_format)
            sheet.write(row, 2, coupon.prefix or '', cell_format)
            sheet.write(row, 3, coupon.store_id.display_name or '', cell_format)
            sheet.write(row, 4, 'Activated', cell_format)
            sheet.write(row, 5, str(coupon.date_activation or ''), cell_format)
            row += 1

        workbook.close()
        output.seek(0)
        excel_data = output.read()

        self.write({
            'file_data': base64.b64encode(excel_data),
            'file_name': 'Activated_Coupons.xlsx',
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f"/web/content/?model={self._name}&id={self.id}&field=file_data&filename_field=file_name&download=true",
            'target': 'self',
        }
