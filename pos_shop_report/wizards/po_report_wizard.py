from odoo import models, fields
from io import BytesIO
import base64
from datetime import datetime, time
import pytz
import xlsxwriter

class PurchaseOrderReportWizard(models.TransientModel):
    _name = 'purchase.order.report.wizard'
    _description = 'Retail DN/PO Confirmed State Update Report Wizard'

    date_from = fields.Date(string="Start Date", required=True)
    date_to = fields.Date(string="End Date", required=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )


    def action_export_xlsx(self):
        self.ensure_one()

        tz = pytz.timezone(self.env.user.tz or 'UTC')
        start_utc = tz.localize(datetime.combine(self.date_from, time.min)).astimezone(pytz.UTC)
        end_utc = tz.localize(datetime.combine(self.date_to, time.max)).astimezone(pytz.UTC)
        purchase_orders = self.env['purchase.order'].sudo().search([
            ('date_order', '>=', start_utc.strftime('%Y-%m-%d %H:%M:%S')),
            ('date_order', '<=', end_utc.strftime('%Y-%m-%d %H:%M:%S')),
            ('company_id', '=', self.company_id.id),
        ], order='date_order asc')

        output = BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('PO Report')
        bold = workbook.add_format({'bold': True, 'border': 1, 'align': 'center', 'valign': 'vcenter'})
        normal = workbook.add_format({'border': 1})

        headers = [
            'Confirmed By', 'Confirmed On', 'ST Date', 'ST No', 'ST Status',
            'ST Type', 'Wh Code', 'Doc Confirmed', 'Updated On'
        ]
        for col, header in enumerate(headers):
            sheet.write(0, col, header, bold)

        sheet.set_column(0, 0, 20)
        sheet.set_column(1, 1, 20)
        sheet.set_column(2, 2, 20)
        sheet.set_column(3, 3, 20)
        sheet.set_column(4, 4, 15)
        sheet.set_column(5, 5, 25)
        sheet.set_column(6, 6, 10)
        sheet.set_column(7, 7, 15)
        sheet.set_column(8, 8, 20)

        row = 1
        for po in purchase_orders:
            sheet.write(row, 0, po.partner_id.name or '', normal)
            sheet.write(row, 1, str(po.date_approve or ''), normal)
            sheet.write(row, 2, str(po.date_order or ''), normal)
            sheet.write(row, 3, po.name or '', normal)
            sheet.write(row, 4, po.state or '', normal)
            sheet.write(row, 5, po.picking_type_id.name if po.picking_type_id else '', normal)
            sheet.write(row, 6, po.picking_type_id.warehouse_id.code if po.picking_type_id.warehouse_id else '', normal)
            sheet.write(row, 7, 'Y' if po.state in ['purchase', 'done'] else 'N', normal)
            sheet.write(row, 8, str(po.write_date or ''), normal)
            row += 1

        workbook.close()
        output.seek(0)
        file_data = base64.b64encode(output.read())
        output.close()

        formatted_date = datetime.now().strftime('%d-%m-%Y')
        attachment = self.env['ir.attachment'].create({
            'name': f"Retail DN/PO Report {formatted_date}.xlsx",
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

