import io
import base64
import pytz
import xlsxwriter
from collections import defaultdict
from datetime import datetime, time
from odoo import models, fields, _
from odoo.exceptions import ValidationError


class TimePeriodSalesReportIndividual(models.TransientModel):
    _name = 'time.period.sales.report.individual'
    _description = 'Time Period Sales Report (Individual Store)'

    shop_id = fields.Many2one('pos.config', string="Shop", required=True)
    from_date = fields.Date(string="From Date", required=True)
    to_date = fields.Date(string="To Date", required=True)

    def action_generate_excel(self):
        company = self.env.company
        user_tz_name = self.env.user.tz or 'UTC'
        user_tz = pytz.timezone(user_tz_name)

        start_utc = user_tz.localize(datetime.combine(self.from_date, time.min)).astimezone(pytz.UTC)
        end_utc = user_tz.localize(datetime.combine(self.to_date, time.max)).astimezone(pytz.UTC)

        orders = self.env['pos.order'].search([
            ('state', 'in', ['paid', 'done', 'invoiced']),
            ('config_id', '=', self.shop_id.id),
            ('date_order', '>=', start_utc.strftime('%Y-%m-%d %H:%M:%S')),
            ('date_order', '<=', end_utc.strftime('%Y-%m-%d %H:%M:%S')),
            ('company_id', '=', company.id),
        ])

        if not orders:
            raise ValidationError(_('There are no orders for this date range.'))

        # FIX: pre-aggregate by hour in ONE pass — no .filtered() in the slot loop
        hour_agg = defaultdict(lambda: {'amount': 0.0, 'count': 0})
        ctx = self.with_context(tz=user_tz_name)
        for order in orders:
            h = fields.Datetime.context_timestamp(ctx, order.date_order).hour
            hour_agg[h]['amount'] += order.amount_total
            hour_agg[h]['count'] += 1

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('時段銷售報告 / Time Period Sales Report')

        bold = workbook.add_format({'bold': True})
        header_format = workbook.add_format({'bold': True, 'align': 'center'})
        money = workbook.add_format({'num_format': '#,##0.00'})
        money_bold = workbook.add_format({'num_format': '#,##0.00', 'bold': True})

        sheet.set_column('A:A', 25)
        sheet.set_column('B:B', 18)
        sheet.set_column('C:C', 15)

        sheet.write(0, 0, company.name, bold)
        sheet.write(1, 0, "時段銷售報告")
        sheet.write(2, 0, "日期區間:")
        sheet.write(2, 1, f"{self.from_date} 至 {self.to_date}")
        sheet.write(3, 0, "分店:")
        sheet.write(3, 1, self.shop_id.name)

        for col, h in enumerate(["銷售時段", "銷售金額($)", "交易次數"]):
            sheet.write(5, col, h, header_format)

        row = 6
        slots = {
            "凌晨(00:00 ~ 06:59)": range(0, 7),
            "早(07:00 ~ 10:59)": range(7, 11),
            "午(11:00 ~ 17:59)": range(11, 18),
            "晚(18:00 ~ 23:59)": range(18, 24),
        }

        grand_total = 0.0
        grand_count = 0

        for slot_name, hours in slots.items():
            sheet.write(row, 0, slot_name, bold)
            row += 1
            slot_total = 0.0
            slot_count = 0
            for hour in hours:
                d = hour_agg[hour]
                sheet.write(row, 0, f"{hour:02d}:00 ~ {hour:02d}:59")
                sheet.write(row, 1, d['amount'] if d['amount'] else "", money)
                sheet.write(row, 2, d['count'] if d['count'] else "")
                slot_total += d['amount']
                slot_count += d['count']
                row += 1
            sheet.write(row, 0, f"{slot_name} 小計", bold)
            sheet.write(row, 1, slot_total, money_bold)
            sheet.write(row, 2, slot_count, bold)
            row += 2
            grand_total += slot_total
            grand_count += slot_count

        sheet.write(row, 0, "總數", bold)
        sheet.write(row, 1, grand_total, money_bold)
        sheet.write(row, 2, grand_count, bold)

        workbook.close()
        output.seek(0)

        filename = f"時段銷售報告 (分店) {self.shop_id.name} {self.from_date} 至 {self.to_date}.xlsx"
        attachment = self.env['ir.attachment'].create({
            'name': filename, 'type': 'binary',
            'datas': base64.b64encode(output.read()),
            'res_model': self._name, 'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        return {'type': 'ir.actions.act_url', 'url': f'/web/content/{attachment.id}?download=true', 'target': 'self'}
