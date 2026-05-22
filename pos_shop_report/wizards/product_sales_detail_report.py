from odoo import models, fields, _
import io
import base64
import pytz
from datetime import datetime, time
from collections import defaultdict
from odoo.tools.misc import xlsxwriter
from odoo.exceptions import ValidationError


class ProductSalesDetailReport(models.TransientModel):
    _name = 'product.sales.detail.report.wizard'
    _description = 'Product Sales Detail Report (Individual Store)'

    from_date = fields.Date('From Date', required=True)
    to_date = fields.Date('To Date', required=True)
    store_id = fields.Many2one('pos.config', string='Store', required=True)

    def action_generate_excel(self):
        company = self.env.company

        tz = pytz.timezone(self.env.user.tz or 'UTC')
        start_utc = tz.localize(datetime.combine(self.from_date, time.min)).astimezone(pytz.UTC)
        end_utc = tz.localize(datetime.combine(self.to_date, time.max)).astimezone(pytz.UTC)

        orders = self.env['pos.order'].search([
            ('date_order', '>=', start_utc),
            ('date_order', '<=', end_utc),
            ('session_id.config_id', '=', self.store_id.id),
            ('state', 'in', ['paid', 'done', 'invoiced']),
            ('company_id', '=', company.id),
        ])
        pos_lines = orders.mapped('lines')

        if not pos_lines:
            raise ValidationError(_('There are no orders for this date range.'))

        # Aggregate by product — consumables and storables
        aggregated = defaultdict(lambda: {'qty': 0.0, 'gross': 0.0, 'product': None})
        for line in pos_lines:
            product = line.product_id
            if product.type not in ('consu', 'product'):
                continue
            key = product.id
            aggregated[key]['product'] = product
            aggregated[key]['qty'] += line.qty
            aggregated[key]['gross'] += line.price_subtotal_incl

        if not aggregated:
            raise ValidationError(_('There are no goods products in orders for this date range.'))

        # Prefetch pos_categ_ids for all products in one query
        all_products = self.env['product.product'].browse([d['product'].id for d in aggregated.values()])
        all_products.mapped('pos_categ_ids')

        def get_primary_categ(product):
            categ = product.pos_categ_ids[0] if product.pos_categ_ids else None
            return categ

        def sort_key(d):
            categ = get_primary_categ(d['product'])
            return (
                categ.sequence if categ else 9999,
                categ.name if categ else '',
                d['product'].default_code or '',
                d['product'].display_name,
            )

        sorted_data = sorted(aggregated.values(), key=sort_key)

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Product Sales Detail Report (Individual Store)')

        bold = workbook.add_format({'bold': True})
        header_format = workbook.add_format({'bold': True, 'align': 'center'})
        normal = workbook.add_format({'align': 'left'})
        categ_format = workbook.add_format({'bold': True, 'align': 'left', 'bg_color': '#D9E1F2'})

        sheet.set_column('A:A', 25)
        sheet.set_column('B:B', 35)
        sheet.set_column('C:C', 10)
        sheet.set_column('D:D', 10)

        sheet.write(0, 0, company.name, bold)
        sheet.write(1, 0, "產品銷售明細報告(個別分店)")
        sheet.write(2, 0, "日期區間:")
        sheet.write(2, 1, f"{self.from_date} 至 {self.to_date}")
        sheet.write(3, 0, "分店:")
        sheet.write(3, 1, self.store_id.name)

        headers = ["產品編號", "產品名稱", "銷售數量", "銷售總額"]
        for col, h in enumerate(headers):
            sheet.write(5, col, h, header_format)

        row = 6
        current_categ_id = -1  # use category ID as the grouping key — unique and unambiguous
        for data in sorted_data:
            product = data['product']
            categ = get_primary_categ(product)
            categ_id = categ.id if categ else 0
            categ_name = categ.name if categ else '(No Category)'

            if categ_id != current_categ_id:
                sheet.merge_range(row, 0, row, 3, categ_name, categ_format)
                current_categ_id = categ_id
                row += 1

            sheet.write(row, 0, product.default_code or '', normal)
            sheet.write(row, 1, product.display_name, normal)
            sheet.write(row, 2, data['qty'], normal)
            sheet.write(row, 3, data['gross'], normal)
            row += 1

        workbook.close()
        output.seek(0)

        filename = f"產品銷售明細報告 (分店) {self.store_id.name} {self.from_date} 至 {self.to_date}.xlsx"
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(output.read()),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }
