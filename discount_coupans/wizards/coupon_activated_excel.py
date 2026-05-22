from datetime import datetime, time
import pytz
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

        tz = pytz.timezone(self.env.user.tz or 'UTC')
        if self.from_date:
            start_utc = tz.localize(datetime.combine(self.from_date, time.min)).astimezone(pytz.UTC)
            domain.append(('date_activation', '>=', start_utc.strftime('%Y-%m-%d %H:%M:%S')))
        if self.to_date:
            end_utc = tz.localize(datetime.combine(self.to_date, time.max)).astimezone(pytz.UTC)
            domain.append(('date_activation', '<=', end_utc.strftime('%Y-%m-%d %H:%M:%S')))

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
            'file_name': f"已生效禮券 {self.from_date.strftime('%Y-%m-%d') if self.from_date else 'all'} 至 {self.to_date.strftime('%Y-%m-%d') if self.to_date else 'all'}.xlsx",
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f"/web/content/?model={self._name}&id={self.id}&field=file_data&filename_field=file_name&download=true",
            'target': 'self',
        }
