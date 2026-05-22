from odoo import models, fields
import io
import base64
import pytz
import xlsxwriter
from collections import defaultdict
from datetime import datetime, time


class TimePeriodSalesReportAll(models.TransientModel):
    _name = 'time.period.sales.report.all'
    _description = 'Time Period Sales Wizard (All Stores)'

    from_date = fields.Date(string="From Date", required=True)
    to_date = fields.Date(string="To Date", required=True)

    def action_generate_excel(self):
        company = self.env.company
        user_tz_name = self.env.user.tz or 'UTC'
        user_tz = pytz.timezone(user_tz_name)

        start_utc = user_tz.localize(datetime.combine(self.from_date, time.min)).astimezone(pytz.UTC)
        end_utc = user_tz.localize(datetime.combine(self.to_date, time.max)).astimezone(pytz.UTC)

        slots = {
            "凌晨(00:00 ~ 06:59)": range(0, 7),
            "早(07:00 ~ 10:59)": range(7, 11),
            "午(11:00 ~ 17:59)": range(11, 18),
            "晚(18:00 ~ 23:59)": range(18, 24),
        }

        stores = self.env['pos.config'].search([])

        # FIX: fetch all orders for all stores in ONE query, then aggregate
        # in a single Python pass — no .filtered() per hour per store, no double loop.
        all_orders = self.env['pos.order'].search_read(
            [
                ('state', 'in', ['paid', 'done', 'invoiced']),
                ('date_order', '>=', start_utc.strftime('%Y-%m-%d %H:%M:%S')),
                ('date_order', '<=', end_utc.strftime('%Y-%m-%d %H:%M:%S')),
                ('company_id', '=', company.id),
            ],
            ['config_id', 'date_order', 'amount_total'],
        )

        ctx = self.with_context(tz=user_tz_name)

        # agg[store_id][hour] = {'amount': X, 'count': Y}
        agg = defaultdict(lambda: defaultdict(lambda: {'amount': 0.0, 'count': 0}))
        store_ids_with_data = set()
        for o in all_orders:
            sid = o['config_id'][0]
            h = fields.Datetime.context_timestamp(ctx, o['date_order']).hour
            agg[sid][h]['amount'] += o['amount_total']
            agg[sid][h]['count'] += 1
            store_ids_with_data.add(sid)

        stores_with_data = [s for s in stores if s.id in store_ids_with_data]

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('時段銷售報告(全線) / Time Period Sales Report (All Stores)')

        bold = workbook.add_format({'bold': True})
        header_format = workbook.add_format({'bold': True, 'align': 'center', 'valign': 'vcenter', 'border': 1})
        money = workbook.add_format({'num_format': '#,##0.00', 'align': 'right'})
        money_bold = workbook.add_format({'num_format': '#,##0.00', 'bold': True})

        sheet.set_column(0, 0, 25)
        sheet.set_column('B:AA', 18)

        sheet.write(0, 0, company.name, bold)
        sheet.write(1, 0, "時段銷售報告(全線)")
        sheet.write(2, 0, "日期區間:")
        sheet.write(2, 1, f"{self.from_date} 至 {self.to_date}")

        col = 1
        for store in stores_with_data:
            sheet.merge_range(4, col, 4, col + 1, store.name, header_format)
            sheet.write(5, col, "銷售金額($)", header_format)
            sheet.write(5, col + 1, "交易次數", header_format)
            col += 2
        sheet.merge_range(4, col, 4, col + 1, "Total", header_format)
        sheet.write(5, col, "總銷售金額($)", header_format)
        sheet.write(5, col + 1, "總交易次數", header_format)

        row = 6
        grand_totals = {s.id: {'amount': 0.0, 'count': 0} for s in stores_with_data}
        grand_total_amount_all = 0.0
        grand_total_count_all = 0

        for slot_name, hours in slots.items():
            sheet.write(row, 0, slot_name, bold)
            row += 1
            for hour in hours:
                sheet.write(row, 0, f"{hour:02d}:00 ~ {hour:02d}:59")
                col = 1
                total_amount_all = 0.0
                total_count_all = 0
                for store in stores_with_data:
                    d = agg[store.id][hour]
                    if d['amount'] or d['count']:
                        sheet.write(row, col,     d['amount'], money)
                        sheet.write(row, col + 1, d['count'])
                    col += 2
                    total_amount_all += d['amount']
                    total_count_all  += d['count']
                    grand_totals[store.id]['amount'] += d['amount']
                    grand_totals[store.id]['count']  += d['count']
                sheet.write(row, col,     total_amount_all if total_amount_all else "", money)
                sheet.write(row, col + 1, total_count_all  if total_count_all  else "")
                grand_total_amount_all += total_amount_all
                grand_total_count_all  += total_count_all
                row += 1
            row += 1

        sheet.write(row, 0, "總數", bold)
        col = 1
        for store in stores_with_data:
            sheet.write(row, col,     grand_totals[store.id]['amount'], money_bold)
            sheet.write(row, col + 1, grand_totals[store.id]['count'],  bold)
            col += 2
        sheet.write(row, col,     grand_total_amount_all, money_bold)
        sheet.write(row, col + 1, grand_total_count_all,  bold)

        workbook.close()
        output.seek(0)

        filename = f"時段銷售報告 (全線) {self.from_date} 至 {self.to_date}.xlsx"
        attachment = self.env['ir.attachment'].create({
            'name': filename, 'type': 'binary',
            'datas': base64.b64encode(output.read()),
            'res_model': self._name, 'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        return {'type': 'ir.actions.act_url', 'url': f'/web/content/{attachment.id}?download=true', 'target': 'self'}
