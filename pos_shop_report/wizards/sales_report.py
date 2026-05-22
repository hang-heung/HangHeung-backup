from odoo import models, fields
import base64
import io
import xlsxwriter
import pytz
from datetime import datetime, date, time
from collections import defaultdict
from odoo.exceptions import ValidationError


class SalesReportExcelWizard(models.TransientModel):
    _name = 'sales.report.excel.wizard'
    _description = 'Sales Report Excel Wizard'

    def default_start_date(self):
        today = date.today()
        return today.replace(day=1)

    file_data = fields.Binary('Excel File', readonly=True)
    file_name = fields.Char('File Name', readonly=True)
    start_date = fields.Date('Start Date', default=default_start_date)
    end_date = fields.Date('End Date', default=fields.Date.context_today)
    pos = fields.Many2one('pos.config')

    def _get_utc_bounds(self):
        """Return (start_utc, end_utc) as timezone-aware UTC datetimes."""
        tz = pytz.timezone(self.env.user.tz or 'UTC')
        start_utc = tz.localize(datetime.combine(self.start_date, time.min)).astimezone(pytz.UTC)
        end_utc = tz.localize(datetime.combine(self.end_date, time.max)).astimezone(pytz.UTC)
        return start_utc, end_utc

    def _aggregate_report_data(self):
        self.ensure_one()
        start_utc, end_utc = self._get_utc_bounds()

        domain = [
            ('state', 'in', ['paid', 'done', 'invoiced']),
            ('date_order', '>=', start_utc),
            ('date_order', '<=', end_utc),
        ]
        cancel_domain = [
            ('state', 'in', ['cancel']),
            ('date_order', '>=', start_utc),
            ('date_order', '<=', end_utc),
        ]
        if self.pos:
            domain.append(('config_id', '=', self.pos.id))
            cancel_domain.append(('config_id', '=', self.pos.id))

        orders = self.env['pos.order'].search(domain)
        cancel_orders = self.env['pos.order'].search(cancel_domain)
        if not orders and not cancel_orders:
            raise ValidationError("No POS orders found for the selected date range and POS.")

        order_total = sum(o.amount_total for o in orders)

        cancel_order_total = 0.0
        cancel_qty = 0.0
        void_by_method = defaultdict(lambda: {"amount": 0.0, "quantity": 0.0})
        for order in cancel_orders:
            cancel_order_total += order.amount_total
            order_qty = sum(line.qty for line in order.lines)
            cancel_qty += order_qty
            payments = order.payment_ids
            if not payments:
                void_by_method["(No Payment)"]["quantity"] += order_qty
                continue
            n_payments = len(payments)
            for payment in payments:
                method = payment.payment_method_id.name or "Unknown"
                void_by_method[method]["amount"] += payment.amount
                void_by_method[method]["quantity"] += order_qty / n_payments

        coupon_program_types = ('coupons', 'gift_card', 'ewallet')
        coupon_redemption = defaultdict(lambda: {"amount": 0.0, "quantity": 0})
        discount_summary = defaultdict(lambda: {"amount": 0.0, "quantity": 0})
        for line in orders.mapped("lines"):
            if not line.is_reward_line or not line.reward_id:
                continue
            program = line.reward_id.program_id
            name = program.name or "Unknown"
            if program.program_type in coupon_program_types:
                coupon_redemption[name]["amount"] += abs(line.price_subtotal_incl)
                coupon_redemption[name]["quantity"] += 1
            else:
                discount_summary[name]["amount"] += abs(line.price_subtotal_incl)
                discount_summary[name]["quantity"] += 1

        total_amount = 0.0
        total_transcation = len(orders)
        payment_summary = defaultdict(lambda: {"total_amount": 0.0, "transactions": 0})
        for payment in orders.mapped("payment_ids"):
            method = payment.payment_method_id.name or "Unknown"
            payment_summary[method]["total_amount"] += payment.amount
            payment_summary[method]["transactions"] += 1
            total_amount += payment.amount

        return {
            'start_date': self.start_date.strftime('%Y-%m-%d') if self.start_date else '',
            'end_date': self.end_date.strftime('%Y-%m-%d') if self.end_date else '',
            'pos_name': self.pos.name if self.pos else '',
            'order_total': order_total,
            'cancel_order_total': cancel_order_total,
            'cancel_qty': cancel_qty,
            'total_amount': total_amount,
            'total_transcation': total_transcation,
            'payment_summary': [
                {'method': k, 'amount': v['total_amount'], 'transactions': v['transactions']}
                for k, v in payment_summary.items()
            ],
            'void_by_method': [
                {'method': k, 'amount': v['amount'], 'quantity': v['quantity']}
                for k, v in void_by_method.items()
            ],
            'coupon_redemption': [
                {'name': k, 'amount': v['amount'], 'quantity': v['quantity']}
                for k, v in coupon_redemption.items()
            ],
            'discount_summary': [
                {'name': k, 'amount': v['amount'], 'quantity': v['quantity']}
                for k, v in discount_summary.items()
            ],
        }

    def action_generate_pdf(self):
        self.ensure_one()
        return self.env.ref('pos_shop_report.action_sales_report_pdf').report_action(self)

    def action_generate_excel(self):
        """Generate POS Sales Excel and attach"""
        data = self._aggregate_report_data()

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet("Sales Report")

        header_format = workbook.add_format({'bold': True, 'bg_color': '#D9E1F2', 'border': 1, 'align': 'left'})
        cell_format = workbook.add_format({'text_wrap': True, 'valign': 'top', 'align': 'left'})
        cell_value_format = workbook.add_format({'text_wrap': True, 'valign': 'top', 'border': 1, 'align': 'left'})
        cell_value_format_bold = workbook.add_format({'bold': True, 'text_wrap': True, 'valign': 'top', 'border': 1, 'align': 'left'})

        sheet.set_column(0, 0, 20, cell_format)
        sheet.set_column(1, 1, 20, cell_format)
        sheet.set_column(2, 2, 30, cell_format)
        sheet.set_column(3, 3, 30, cell_format)
        sheet.set_column(4, 4, 30, cell_format)

        order_total = data['order_total']
        cancel_order_total = data['cancel_order_total']
        cancel_qty = data['cancel_qty']
        total_amount = data['total_amount']
        total_transcation = data['total_transcation']
        payment_summary = {p['method']: {'total_amount': p['amount'], 'transactions': p['transactions']} for p in data['payment_summary']}
        void_by_method = {v['method']: {'amount': v['amount'], 'quantity': v['quantity']} for v in data['void_by_method']}
        coupon_redemption = {c['name']: {'amount': c['amount'], 'quantity': c['quantity']} for c in data['coupon_redemption']}
        discount_summary = {d['name']: {'amount': d['amount'], 'quantity': d['quantity']} for d in data['discount_summary']}

        row = 1
        sheet.write(row, 0, "日期:", header_format)
        sheet.write(row, 1, self.start_date.strftime('%Y-%m-%d'), cell_value_format)
        row += 1
        sheet.write(row, 0, "(日結)時間:", header_format)
        sheet.write(row, 1, self.end_date.strftime('%Y-%m-%d'), cell_value_format)

        row += 1
        sheet.write(row, 0, "分店:", header_format)
        sheet.write(row, 1, self.pos.name if self.pos else '', cell_value_format)

        row += 1
        sheet.write(row, 0, "總計($) :", header_format)
        sheet.write(row, 1, order_total, cell_value_format)

        row += 1
        sheet.write(row, 0, "交易數量 :", header_format)
        sheet.write(row, 1, total_transcation, cell_value_format)

        row += 2
        sheet.write(row, 0, "支付方式", header_format)
        sheet.write(row, 1, "Amount", header_format)
        sheet.write(row, 2, "Transactions", header_format)
        row += 1
        for method, vals in payment_summary.items():
            sheet.write(row, 0, method, cell_value_format)
            sheet.write_number(row, 1, vals["total_amount"], cell_value_format)
            sheet.write_number(row, 2, vals["transactions"], cell_value_format)
            row += 1
        sheet.write(row, 0, "淨收入:", cell_value_format_bold)
        sheet.write(row, 1, total_amount, cell_value_format)
        sheet.write(row, 2, total_transcation, cell_value_format)

        row += 2
        sheet.write(row, 0, "Void單", header_format)
        sheet.write(row, 1, "Amount", header_format)
        sheet.write(row, 2, "Quantity", header_format)
        row += 1
        for method, vals in void_by_method.items():
            sheet.write(row, 0, method, cell_value_format)
            sheet.write_number(row, 1, vals["amount"], cell_value_format)
            sheet.write_number(row, 2, vals["quantity"], cell_value_format)
            row += 1
        sheet.write(row, 0, "總計:", cell_value_format_bold)
        sheet.write_number(row, 1, cancel_order_total, cell_value_format)
        sheet.write_number(row, 2, cancel_qty, cell_value_format)

        row += 2
        sheet.write(row, 0, "咭類兌換", header_format)
        sheet.write(row, 1, "Amount Redeemed", header_format)
        sheet.write(row, 2, "Quantity Redeemed", header_format)
        row += 1
        coupon_total_amount = 0.0
        coupon_total_qty = 0
        for coupon_name, vals in coupon_redemption.items():
            sheet.write(row, 0, coupon_name, cell_value_format)
            sheet.write_number(row, 1, vals["amount"], cell_value_format)
            sheet.write_number(row, 2, vals["quantity"], cell_value_format)
            coupon_total_amount += vals["amount"]
            coupon_total_qty += vals["quantity"]
            row += 1
        sheet.write(row, 0, "總計:", cell_value_format_bold)
        sheet.write_number(row, 1, coupon_total_amount, cell_value_format)
        sheet.write_number(row, 2, coupon_total_qty, cell_value_format)

        row += 2
        sheet.write(row, 0, "Discount", header_format)
        sheet.write(row, 1, "Amount", header_format)
        sheet.write(row, 2, "Qty", header_format)
        row += 1
        discount_total_amount = 0.0
        discount_total_qty = 0
        for name, vals in discount_summary.items():
            sheet.write(row, 0, name, cell_value_format)
            sheet.write_number(row, 1, vals["amount"], cell_value_format)
            sheet.write_number(row, 2, vals["quantity"], cell_value_format)
            discount_total_amount += vals["amount"]
            discount_total_qty += vals["quantity"]
            row += 1
        sheet.write(row, 0, "總計:", cell_value_format_bold)
        sheet.write_number(row, 1, discount_total_amount, cell_value_format)
        sheet.write_number(row, 2, discount_total_qty, cell_value_format)

        workbook.close()
        output.seek(0)
        excel_data = output.read()

        filename = f"日結報表(分店) {self.pos.name + ' ' if self.pos else ''}{self.start_date.strftime('%Y-%m-%d')} 至 {self.end_date.strftime('%Y-%m-%d')}.xlsx"
        self.write({
            'file_data': base64.b64encode(excel_data),
            'file_name': filename,
        })
        self.env['ir.attachment'].create({
            'name': filename,
            'datas': base64.b64encode(excel_data),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f"/web/content/?model={self._name}&id={self.id}&field=file_data&filename_field=file_name&download=true",
            'target': 'self',
        }
