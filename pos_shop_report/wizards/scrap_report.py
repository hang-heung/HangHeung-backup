from odoo import models, fields, api
from odoo.exceptions import ValidationError
from io import BytesIO
import base64
from datetime import datetime, time
import pytz
import xlsxwriter

class ScrapReportWizard(models.TransientModel):
    _name = 'scrap.report.wizard'
    _description = 'Scrap Report Wizard'

    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
    shop_ids = fields.Many2many(
        'stock.warehouse',
        string='Warehouses',
        required=True,
    )
    scrap_ids = fields.Many2many('stock.scrap', string="Scraps")

    def action_export_xlsx(self):
        self.ensure_one()
        if not self.shop_ids:
            raise ValidationError("Please select at least one warehouse.")

        view_location_ids = self.shop_ids.mapped('view_location_id').ids
        scrap_locations = self.env['stock.location'].search([
            ('location_id', 'child_of', view_location_ids)
        ])

        tz = pytz.timezone(self.env.user.tz or 'UTC')
        start_utc = tz.localize(datetime.combine(self.date_from, time.min)).astimezone(pytz.UTC)
        end_utc = tz.localize(datetime.combine(self.date_to, time.max)).astimezone(pytz.UTC)
        scraps = self.env['stock.scrap'].search([
            ('location_id', 'in', scrap_locations.ids),
            ('date_done', '>=', start_utc.strftime('%Y-%m-%d %H:%M:%S')),
            ('date_done', '<=', end_utc.strftime('%Y-%m-%d %H:%M:%S')),
            ('state', '=', 'done'),
        ])

        output = BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Shop write of Report')

        bold = workbook.add_format({'bold': True, 'border': 1})
        normal = workbook.add_format({'border': 1})

        headers = [
            'Shop Code', 'Warehouse', 'Item Code', 'Item Name',
            'Item Quantity', 'Transaction Date', 'Transaction No', 'Reason Code'
        ]
        for col, header in enumerate(headers):
            sheet.write(0, col, header, bold)

        sheet.set_column(0, 0, 20)
        sheet.set_column(1, 1, 25)
        sheet.set_column(2, 2, 15)
        sheet.set_column(3, 3, 30)
        sheet.set_column(4, 4, 12)
        sheet.set_column(5, 5, 20)
        sheet.set_column(6, 6, 20)
        sheet.set_column(7, 7, 25)

        # Build location_id → warehouse map once — avoids N+1 queries (BUG-11)
        loc_to_warehouse = {}
        for wh in self.shop_ids:
            child_loc_ids = self.env['stock.location'].search([
                ('id', 'child_of', wh.view_location_id.id)
            ]).ids
            for loc_id in child_loc_ids:
                loc_to_warehouse[loc_id] = wh

        row = 1
        for scrap in scraps:
            warehouse = loc_to_warehouse.get(scrap.location_id.id)

            reason = ', '.join(scrap.scrap_reason_tag_ids.mapped('name')) if scrap.scrap_reason_tag_ids else ''

            sheet.write(row, 0, scrap.location_id.name or '', normal)
            sheet.write(row, 1, warehouse.name or '', normal)
            sheet.write(row, 2, scrap.product_id.default_code or '', normal)
            sheet.write(row, 3, scrap.product_id.name or '', normal)
            sheet.write(row, 4, scrap.scrap_qty or 0, normal)
            sheet.write(row, 5, str(scrap.date_done or ''), normal)
            sheet.write(row, 6, scrap.name or '', normal)
            sheet.write(row, 7, reason, normal)
            row += 1

        workbook.close()
        output.seek(0)

        file_data = base64.b64encode(output.read())
        output.close()

        formatted_date = datetime.now().strftime('%d-%m-%Y')
        attachment = self.env['ir.attachment'].create({
            'name': f"Shop write off {formatted_date}.xlsx",
            'type': 'binary',
            'datas': file_data,
            'res_model': self._name,
            'res_id': self.id,
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

