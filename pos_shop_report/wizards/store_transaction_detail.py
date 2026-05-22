from odoo import models, fields, _
import io
import pytz
import xlsxwriter
import base64
from collections import defaultdict
from datetime import datetime, time
from odoo.exceptions import ValidationError


class POSShopStoreTransactionWizard(models.TransientModel):
    _name = 'pos.shop.store.transaction.report.wizard'
    _description = 'POS Shop Store Transaction Report Wizard'

    shop_id = fields.Many2one('pos.config', string='Shop', required=True)
    date_start = fields.Date(string='Start Date', required=True)
    date_end = fields.Date(string='End Date', required=True)

    def generate_report(self):
        company = self.env.company
        user_tz = pytz.timezone(self.env.user.tz or 'UTC')

        start_utc = user_tz.localize(datetime.combine(self.date_start, time.min)).astimezone(pytz.UTC)
        end_utc = user_tz.localize(datetime.combine(self.date_end, time.max)).astimezone(pytz.UTC)

        orders = self.env['pos.order'].search([
            ('config_id', '=', self.shop_id.id),
            ('date_order', '>=', start_utc.strftime('%Y-%m-%d %H:%M:%S')),
            ('date_order', '<=', end_utc.strftime('%Y-%m-%d %H:%M:%S')),
            ('company_id', '=', company.id),
        ])

        if not orders:
            raise ValidationError(_('There are no orders for this date.'))

        # FIX: pre-fetch ALL lines and ALL payments in two queries instead of
        # lazy-loading order.lines per order (N+1 queries for each order).
        all_lines = self.env['pos.order.line'].search_read(
            [('order_id', 'in', orders.ids)],
            ['order_id', 'product_id', 'qty'],
            order='order_id, id',
        )
        all_payments = self.env['pos.payment'].search_read(
            [('pos_order_id', 'in', orders.ids)],
            ['pos_order_id', 'payment_method_id', 'transaction_id', 'amount'],
        )

        # Build lookup dicts
        lines_by_order = defaultdict(list)
        for ln in all_lines:
            lines_by_order[ln['order_id'][0]].append(ln)

        payments_by_order = defaultdict(list)
        for p in all_payments:
            payments_by_order[p['pos_order_id'][0]].append(p)

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet("分店交易明細")

        title_format = workbook.add_format({'bold': True, 'font_size': 14})
        header_format = workbook.add_format({'bold': True, 'border': 1})
        wrap_format = workbook.add_format({'text_wrap': True})

        row = 0
        worksheet.write(row, 0, company.name, title_format); row += 1
        worksheet.write(row, 0, "分店交易明細", title_format); row += 2

        headers = ["日期", "交易時間", "分店", "訂單編號", "訂單內容", "數量", "交易金額", "付款方式", "電子支付參考編號", "備註"]
        col_widths = [len(h) for h in headers]
        for col, h in enumerate(headers):
            worksheet.write(row, col, h, header_format)
        row += 1

        for order in orders:
            local_dt = fields.Datetime.context_timestamp(self, order.date_order)
            order_lines = lines_by_order.get(order.id, [])
            order_payments = payments_by_order.get(order.id, [])

            payment_methods = ', '.join(
                p['payment_method_id'][1] for p in order_payments
            ) if order_payments else ''
            payment_refs = ', '.join(
                p['transaction_id'] for p in order_payments if p.get('transaction_id')
            ) if order_payments else ''

            first_line = True
            for ln in order_lines:
                product_name = ln['product_id'][1] if ln['product_id'] else ''
                if first_line:
                    values = [
                        local_dt.date().strftime("%d/%m/%Y"),
                        local_dt.strftime("%H:%M:%S"),
                        order.config_id.name,
                        order.pos_reference or order.name,
                        product_name,
                        str(int(ln['qty'])),
                        f"{order.amount_total:.2f}",
                        payment_methods,
                        payment_refs,
                        order.general_note or '',
                    ]
                    first_line = False
                else:
                    values = ["", "", "", "", product_name, str(int(ln['qty'])), "", "", "", ""]

                for col, val in enumerate(values):
                    worksheet.write(row, col, val, wrap_format if col == 4 else None)
                    col_widths[col] = max(col_widths[col], len(str(val)))
                row += 1

        for i, width in enumerate(col_widths):
            worksheet.set_column(i, i, width + 2)

        workbook.close()
        output.seek(0)

        filename = f"分店交易明細 {self.shop_id.name} {self.date_start.strftime('%Y-%m-%d')} 至 {self.date_end.strftime('%Y-%m-%d')}.xlsx"
        attachment = self.env['ir.attachment'].create({
            'name': filename, 'type': 'binary',
            'datas': base64.b64encode(output.read()),
            'res_model': self._name, 'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        return {'type': 'ir.actions.act_url', 'url': f'/web/content/{attachment.id}?download=true', 'target': 'self'}
