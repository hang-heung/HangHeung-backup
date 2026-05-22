from odoo import models, fields, api, _
import base64
import io
import xlsxwriter
import pytz
from datetime import datetime, time
from odoo.exceptions import ValidationError

class CouponSummaryExcelWizard(models.TransientModel):
    _name = 'coupon.summary.excel.wizard'
    _description = 'Coupon Summary Excel Report Wizard'

    from_date = fields.Date('From Date', required=True)
    to_date = fields.Date('To Date', required=True)
    program_ids = fields.Many2many('loyalty.program', string="Coupon Programs", domain="[('program_type', '=', 'coupons')]",required=True)
    activated_shop_ids = fields.Many2many(
        'pos.config',
        'coupon_summary_activated_shop_rel',
        'wizard_id',
        'shop_id',
        string="Activated Shops",
    )

    sold_shop_ids = fields.Many2many(
        'pos.config',
        'coupon_summary_sold_shop_rel',
        'wizard_id',
        'shop_id',
        string="Redeemed Shops"
    )
    file_data = fields.Binary('Excel File', readonly=True)
    file_name = fields.Char('File Name', readonly=True)

    def action_generate_report_excel(self):
        # FIX 1: date filter uses date_activation (when coupon was distributed to a shop),
        # not create_date (when the batch record was bulk-generated — often months prior).
        # FIX 2: shop filter uses OR across allocated_store_id and redeem_shop_id so
        # selecting a shop returns coupons where EITHER field matches (not both required).
        tz = pytz.timezone(self.env.user.tz or 'UTC')
        domain = [('program_id', 'in', self.program_ids.ids)] if self.program_ids else []

        if self.from_date:
            start_utc = tz.localize(datetime.combine(self.from_date, time.min)).astimezone(pytz.UTC)
            domain.append(('date_activation', '>=', start_utc.strftime('%Y-%m-%d %H:%M:%S')))
        if self.to_date:
            end_utc = tz.localize(datetime.combine(self.to_date, time.max)).astimezone(pytz.UTC)
            domain.append(('date_activation', '<=', end_utc.strftime('%Y-%m-%d %H:%M:%S')))

        # Each shop filter applies only to its own field (independent AND conditions)
        if self.activated_shop_ids:
            domain.append(('allocated_store_id', 'in', self.activated_shop_ids.ids))
        if self.sold_shop_ids:
            domain.append(('redeem_shop_id', 'in', self.sold_shop_ids.ids))

        coupons = self.env['loyalty.card'].search(domain)
        if not coupons:
            raise ValidationError(_("No data found for the selected filters, Excel file will not be generated."))

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Coupon Summary')

        header_format = workbook.add_format({
            'bold': True, 'bg_color': '#D9D9D9', 'align': 'center', 'valign': 'vcenter'
        })
        cell = workbook.add_format({'text_wrap': True, 'valign': 'top'})

        headers = [
            'Code', 'Prefix', 'Coupon Program', 'Activated Shop', 'Redeemed Shop',
            'Status', 'Activation Date', 'Redeemed Date', 'Created Date'
        ]

        for col, title in enumerate(headers):
            sheet.write(0, col, title, header_format)

        row = 1
        for c in coupons:
            sheet.write(row, 0, c.code or '', cell)
            sheet.write(row, 1, c.prefix or '', cell)
            sheet.write(row, 2, c.program_id.name or '', cell)
            sheet.write(row, 3, c.allocated_store_id.display_name or '', cell)
            sheet.write(row, 4, c.redeem_shop_id.display_name or '', cell)
            sheet.write(row, 5, c.status.title() or '', cell)
            sheet.write(row, 6, str(c.date_activation or ''), cell)
            sheet.write(row, 7, str(c.redeemed_datetime or ''), cell)
            sheet.write(row, 8, str(c.create_date.date() if c.create_date else ''), cell)
            row += 1

        workbook.close()
        output.seek(0)

        self.write({
            'file_data': base64.b64encode(output.read()),
            'file_name': f"禮券生效及兌換報表 {self.from_date.strftime('%Y-%m-%d')} 至 {self.to_date.strftime('%Y-%m-%d')}.xlsx"
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f"/web/content/?model={self._name}&id={self.id}&field=file_data&filename_field=file_name&download=true",
            'target': 'self',
        }
