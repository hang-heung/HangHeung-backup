from datetime import datetime, time
import pytz
from odoo import models, fields
import base64
import io
import xlsxwriter


class CouponUsedExcelWizard(models.TransientModel):
    _name = 'coupon.used.excel.wizard'
    _description = 'Used Coupon Excel Wizard'

    from_date = fields.Date('From Date')
    to_date = fields.Date('To Date')
    file_data = fields.Binary('Excel File', readonly=True)
    file_name = fields.Char('File Name', readonly=True)

    def action_generate_excel(self):
        domain = [
            ('status', '=', 'redeemed'),
            ('program_id.program_type', '=', 'coupons')
        ]

        # FIX: use redeemed_datetime (set at actual redemption) instead of
        # write_date which changes on any field update and gives wrong results.
        tz = pytz.timezone(self.env.user.tz or 'UTC')
        if self.from_date:
            start_utc = tz.localize(datetime.combine(self.from_date, time.min)).astimezone(pytz.UTC)
            domain.append(('redeemed_datetime', '>=', start_utc.strftime('%Y-%m-%d %H:%M:%S')))
        if self.to_date:
            end_utc = tz.localize(datetime.combine(self.to_date, time.max)).astimezone(pytz.UTC)
            domain.append(('redeemed_datetime', '<=', end_utc.strftime('%Y-%m-%d %H:%M:%S')))

        coupons = self.env['loyalty.card'].search(domain)

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Used Coupons')

        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#C9DAF8',
            'align': 'center',
            'valign': 'vcenter'
        })
        cell_format = workbook.add_format({'text_wrap': True, 'valign': 'top'})

        headers = ['Program Name', 'Code', 'Prefix', 'Redeem Store', 'Status', 'Activation Store']

        sheet.set_column(0, 0, 30, cell_format)
        sheet.set_column(1, 1, 20, cell_format)
        sheet.set_column(2, 2, 15, cell_format)
        sheet.set_column(3, 3, 30, cell_format)
        sheet.set_column(4, 4, 20, cell_format)
        sheet.set_column(5, 5, 30, cell_format)

        for col, head in enumerate(headers):
            sheet.write(0, col, head, header_format)

        row = 1
        for coupon in coupons:
            sheet.write(row, 0, coupon.program_id.name or '', cell_format)
            sheet.write(row, 1, coupon.code or '', cell_format)
            sheet.write(row, 2, coupon.prefix or '', cell_format)
            # HH-CUSTOM: 'Store' column was reading store_id which is NULL
            # on every redeemed coupon. The correct source is
            # redeem_shop_id (set when the coupon is actually redeemed).
            sheet.write(row, 3, coupon.redeem_shop_id.display_name or '', cell_format)
            sheet.write(row, 4, 'Redeemed', cell_format)
            sheet.write(row, 5, coupon.activation_store_id.display_name or '', cell_format)
            row += 1

        workbook.close()
        output.seek(0)
        excel_data = output.read()

        self.write({
            'file_data': base64.b64encode(excel_data),
            'file_name': f"禮券兌換報告 (按舖) {self.from_date.strftime('%Y-%m-%d') if self.from_date else 'all'} 至 {self.to_date.strftime('%Y-%m-%d') if self.to_date else 'all'}.xlsx",
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f"/web/content/?model={self._name}&id={self.id}&field=file_data&filename_field=file_name&download=true",
            'target': 'self',
        }
