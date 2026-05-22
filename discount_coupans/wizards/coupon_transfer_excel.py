from odoo import models, fields, api, _
from odoo.exceptions import UserError
import io
import re
import base64
import xlsxwriter
from datetime import datetime

class CouponTransferExcelWizard(models.TransientModel):
    _name = 'coupon.transfer.excel.wizard'
    _description = 'Transfer Coupon Excel Wizard'

    shop_ids = fields.Many2many('pos.config', string='Shops')
    from_date = fields.Date('From Date', required=True)
    to_date = fields.Date('To Date', required=True)
    file = fields.Binary('Excel File')
    filename = fields.Char('File Name')

    def action_generate_transfer_excel(self):
        if self.from_date > self.to_date:
            raise UserError(_('From Date must be before or equal to To Date.'))

        domain = [
            ('allocated_date', '>=', self.from_date),
            ('allocated_date', '<=', self.to_date),
        ]
        if self.shop_ids:
            domain.append(('allocated_store_id', 'in', self.shop_ids.ids))

        cards = self.env['loyalty.card'].search(domain, order='allocated_store_id, program_id, code')

        if not cards:
            raise UserError(_('No coupons found for the selected store(s) and date range.'))


        coupon_data = {}

        for card in cards:
            store = card.allocated_store_id
            program = card.program_id
            if store.id not in coupon_data:
                coupon_data[store.id] = {'store': store, 'programs': {}}
            prog_dict = coupon_data[store.id]['programs']
            if program.id not in prog_dict:
                prog_dict[program.id] = {
                    'program': program,
                    'codes': [card.code],
                    'min_date': card.allocated_date,
                    'max_date': card.allocated_date,
                }
            else:
                entry = prog_dict[program.id]
                entry['codes'].append(card.code)
                if card.allocated_date and entry['min_date'] and card.allocated_date < entry['min_date']:
                    entry['min_date'] = card.allocated_date
                if card.allocated_date and entry['max_date'] and card.allocated_date > entry['max_date']:
                    entry['max_date'] = card.allocated_date

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output)
        worksheet = workbook.add_worksheet('Coupon Transfer')

        worksheet.set_column('A:A', 25)
        worksheet.set_column('B:B', 30)
        worksheet.set_column('C:C', 80)
        worksheet.set_column('D:E', 18)

        title_format = workbook.add_format({'bold': True, 'font_size': 14})
        header_format = workbook.add_format({'bold': True, 'bg_color': '#D3D3D3'})

        worksheet.write('A1', '禮券到舖表', title_format)
        worksheet.write('A2', '產生 日期：')
        worksheet.write('B2', fields.Date.context_today(self).strftime("%d/%m/%Y"))
        worksheet.write('A3', '店舖 (選取)')
        shop_names = ', '.join([s.name for s in (self.shop_ids or self.env['pos.config'].browse([]))]) if self.shop_ids else 'All Stores'
        worksheet.write('B3', shop_names)
        worksheet.write('A4', '日期範圍')
        worksheet.write('B4', f"{self.from_date.strftime('%d/%m/%Y')} - {self.to_date.strftime('%d/%m/%Y')}")

        row = 5
        worksheet.write(row, 0, 'Store', header_format)
        worksheet.write(row, 1, 'Coupon Name', header_format)
        worksheet.write(row, 2, 'Coupon Codes', header_format)
        worksheet.write(row, 3, 'Earliest Allocated', header_format)
        worksheet.write(row, 4, 'Latest Allocated', header_format)
        row += 1

        for store_id, store_info in coupon_data.items():
            store = store_info['store']
            programs = store_info['programs']
            for prog_id, entry in programs.items():
                program = entry['program']
                codes = sorted(entry['codes'])
                min_date = entry.get('min_date')
                max_date = entry.get('max_date')

                all_codes = ', '.join(codes)

                worksheet.write(row, 0, store.name)
                worksheet.write(row, 1, program.name)
                worksheet.write(row, 2, all_codes)
                worksheet.write(row, 3, min_date.strftime('%d/%m/%Y') if min_date else '')
                worksheet.write(row, 4, max_date.strftime('%d/%m/%Y') if max_date else '')
                row += 1

        workbook.close()
        output.seek(0)
        data = output.read()

        self.file = base64.b64encode(data)
        from_name = self.from_date.strftime('%Y%m%d')
        to_name = self.to_date.strftime('%Y%m%d')
        shops_part = 'All' if not self.shop_ids else '_'.join([s.name.replace(' ', '_') for s in self.shop_ids])
        self.filename = f'禮券到舖表 {self.from_date.strftime("%Y-%m-%d")} 至 {self.to_date.strftime("%Y-%m-%d")}.xlsx'

        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/?model=%s&id=%s&field=file&filename=%s&download=true' % (self._name, self.id, self.filename),
            'target': 'self',
        }
