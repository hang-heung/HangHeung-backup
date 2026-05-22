# -*- coding: utf-8 -*-
import io
import base64
import pytz
import xlsxwriter
from datetime import datetime, time
from odoo import api, fields, models


class PosDetailsWizard(models.TransientModel):
    _inherit = 'pos.details.wizard'

    start_date_only = fields.Date(
        string='Start Date',
        required=True,
        default=lambda self: fields.Date.context_today(self),
    )
    end_date_only = fields.Date(
        string='End Date',
        required=True,
        default=lambda self: fields.Date.context_today(self),
    )

    @api.onchange('start_date_only')
    def _onchange_start_date_only(self):
        if self.start_date_only and self.end_date_only and self.end_date_only < self.start_date_only:
            self.end_date_only = self.start_date_only

    @api.onchange('end_date_only')
    def _onchange_end_date_only(self):
        if self.end_date_only and self.start_date_only and self.end_date_only < self.start_date_only:
            self.start_date_only = self.end_date_only

    def _get_utc_range(self):
        user_tz = pytz.timezone(self.env.user.tz or 'Asia/Hong_Kong')
        start_dt = user_tz.localize(datetime.combine(self.start_date_only, time(0, 0, 0)))
        end_dt   = user_tz.localize(datetime.combine(self.end_date_only,   time(23, 59, 59)))
        start_utc = start_dt.astimezone(pytz.utc).replace(tzinfo=None)
        end_utc   = end_dt.astimezone(pytz.utc).replace(tzinfo=None)
        return fields.Datetime.to_string(start_utc), fields.Datetime.to_string(end_utc)

    def generate_report(self):
        start_utc, end_utc = self._get_utc_range()
        data = {
            'date_start': start_utc,
            'date_stop':  end_utc,
            'config_ids': self.pos_config_ids.ids,
        }
        return self.env.ref('point_of_sale.sale_details_report').report_action([], data=data)

    def generate_excel(self):
        start_utc, end_utc = self._get_utc_range()

        # Re-use the same data pipeline as the PDF report
        report_model = self.env['report.point_of_sale.report_saledetails']
        data = report_model.with_context(tz=self.env.user.tz or 'Asia/Hong_Kong').get_sale_details(
            date_start=start_utc,
            date_stop=end_utc,
            config_ids=self.pos_config_ids.ids,
        )

        currency = data.get('currency', {})
        symbol   = currency.get('symbol', '')
        prec     = currency.get('precision', 2)
        num_fmt  = f'#,##0.{"0" * prec}'

        output   = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        ws       = workbook.add_worksheet('銷售明細')

        # ── Formats ──────────────────────────────────────────────────────────
        fmt_title      = workbook.add_format({'bold': True, 'font_size': 14})
        fmt_section    = workbook.add_format({'bold': True, 'bg_color': '#AAAAAA',
                                              'font_color': '#FFFFFF', 'border': 1})
        fmt_cat        = workbook.add_format({'bold': True, 'bg_color': '#DDDDDD',
                                              'indent': 1})
        fmt_cat_num    = workbook.add_format({'bold': True, 'bg_color': '#DDDDDD',
                                              'num_format': num_fmt})
        fmt_item       = workbook.add_format({'indent': 2})
        fmt_item_num   = workbook.add_format({'num_format': num_fmt})
        fmt_total      = workbook.add_format({'bold': True,
                                              'top': 1, 'bottom': 2})
        fmt_total_num  = workbook.add_format({'bold': True, 'num_format': num_fmt,
                                              'top': 1, 'bottom': 2})
        fmt_pay_hdr    = workbook.add_format({'bold': True, 'bg_color': '#AAAAAA',
                                              'font_color': '#FFFFFF', 'border': 1,
                                              'align': 'center'})
        fmt_pay_label  = workbook.add_format({'bold': True, 'indent': 1})
        fmt_pay_amt    = workbook.add_format({'num_format': num_fmt})
        fmt_col_hdr    = workbook.add_format({'bold': True, 'bottom': 1,
                                              'bg_color': '#F0F0F0'})

        # ── Column widths ────────────────────────────────────────────────────
        ws.set_column(0, 0, 32)   # Product name
        ws.set_column(1, 1, 5)    # (spacer)
        ws.set_column(2, 2, 10)   # Qty
        ws.set_column(3, 3, 16)   # Amount

        row = 0

        # ── Title block ──────────────────────────────────────────────────────
        date_label = data.get('date_start_str', '')
        if data.get('date_stop_str'):
            date_label += ' – ' + data['date_stop_str']

        ws.write(row, 0, '銷售明細', fmt_title)
        row += 1
        if date_label:
            ws.write(row, 0, date_label)
            row += 1
        if data.get('config_names'):
            ws.write(row, 0, ', '.join(data['config_names']))
            row += 1
        row += 1

        # ── Column headers ───────────────────────────────────────────────────
        ws.write(row, 0, '產品',  fmt_col_hdr)
        ws.write(row, 1, '',      fmt_col_hdr)
        ws.write(row, 2, '數量',  fmt_col_hdr)
        ws.write(row, 3, f'金額 ({symbol})', fmt_col_hdr)
        row += 1

        # ── Helper: write one products section ───────────────────────────────
        def write_section(title, categories, totals):
            nonlocal row
            ws.merge_range(row, 0, row, 3, title, fmt_section)
            row += 1
            for cat in categories:
                ws.write(row, 0, cat['name'],  fmt_cat)
                ws.write(row, 1, '',           fmt_cat)
                ws.write(row, 2, cat['qty'],   fmt_cat_num)
                ws.write(row, 3, cat['total'], fmt_cat_num)
                row += 1
                for p in cat['products']:
                    ws.write(row, 0, p['product_name'], fmt_item)
                    ws.write(row, 1, '')
                    ws.write(row, 2, p['quantity'],    fmt_item_num)
                    ws.write(row, 3, p['base_amount'], fmt_item_num)
                    row += 1
            ws.write(row, 0, '總計',          fmt_total)
            ws.write(row, 1, '',              fmt_total)
            ws.write(row, 2, totals['qty'],   fmt_total_num)
            ws.write(row, 3, totals['total'], fmt_total_num)
            row += 2

        if data.get('goods_products'):
            write_section('銷售', data['goods_products'], data['goods_info'])

        if data.get('service_products'):
            write_section('折扣及推廣項目', data['service_products'], data['service_info'])

        if data.get('refund_products'):
            write_section('退款', data['refund_products'], data['refund_info'])

        # ── Payment summary (right-aligned, half-width) ───────────────────────
        if data.get('payments_consolidated'):
            row += 1
            ws.merge_range(row, 2, row, 3, '付款', fmt_pay_hdr)
            row += 1
            for pmt in data['payments_consolidated']:
                ws.write(row, 2, pmt['name'],  fmt_pay_label)
                ws.write(row, 3, pmt['total'], fmt_pay_amt)
                row += 1

        workbook.close()
        output.seek(0)
        excel_b64 = base64.b64encode(output.read()).decode()

        # Build filename
        fn_date = date_label.replace(' – ', '_').replace('年', '').replace('月', '').replace('日', '')
        filename = f'銷售明細_{fn_date}.xlsx'

        # Clean up any old Excel attachments for this wizard model before creating a new one
        # (TransientModel attachments are not cascade-deleted by Odoo's autovacuum)
        self.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'pos.details.wizard'),
            ('name', 'like', '銷售明細_'),
        ]).unlink()

        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'datas': excel_b64,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'res_model': 'pos.details.wizard',
            'res_id': self.id,
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'new',
        }
