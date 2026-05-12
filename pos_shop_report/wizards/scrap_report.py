from odoo import models, fields, api
from odoo.exceptions import ValidationError
from io import BytesIO
import base64
from datetime import datetime
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

        scrap_location_names = scrap_locations.mapped('complete_name')
        scraps = self.env['stock.scrap'].search([
            ('location_id.complete_name', 'in', scrap_location_names),
            ('date_done', '>=', self.date_from),
            ('date_done', '<=', self.date_to),
            ('state', '=', 'done')
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

        row = 1
        for scrap in scraps:
            warehouse = self.env['stock.warehouse'].search([
                ('view_location_id', 'parent_of', scrap.location_id.id)
            ], limit=1)

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

