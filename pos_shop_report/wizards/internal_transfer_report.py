from odoo import models, fields, api
import xlsxwriter
import base64
from io import BytesIO
from datetime import datetime, time
import pytz


class InternalTransferReportWizard(models.TransientModel):
    _name = 'internal.transfer.report.wizard'
    _description = 'Internal Transfer Report Wizard'

    date_from = fields.Date(string="Start Date", required=True)
    date_to = fields.Date(string="End Date", required=True)    

    def action_export_xlsx(self):
        self.ensure_one()
        tz = pytz.timezone(self.env.user.tz or 'UTC')
        start_utc = tz.localize(datetime.combine(self.date_from, time.min)).astimezone(pytz.UTC)
        end_utc = tz.localize(datetime.combine(self.date_to, time.max)).astimezone(pytz.UTC)
        transfers = self.env['stock.picking'].search([
            ('picking_type_code', '=', 'internal'),
            ('scheduled_date', '>=', start_utc.strftime('%Y-%m-%d %H:%M:%S')),
            ('scheduled_date', '<=', end_utc.strftime('%Y-%m-%d %H:%M:%S')),
            ('state', 'not in', ['draft', 'cancel']),
        ])

        output = BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Internal Transfer Report')

        bold = workbook.add_format({'bold': True, 'border': 1})
        normal = workbook.add_format({'border': 1})

        headers = [
            'Trx No', 'Trx Date', 'Sh Code', 'Item Code', 'Item Name',
            'Unit', 'Qty', 'Reason Code', 'Transfer Location'
        ]

        # Write headers
        for col, header in enumerate(headers):
            sheet.write(0, col, header, bold)

        sheet.set_column(0, 0, 15)
        sheet.set_column(1, 1, 20)
        sheet.set_column(2, 2, 25)
        sheet.set_column(3, 3, 15)
        sheet.set_column(4, 4, 30)
        sheet.set_column(5, 5, 10)
        sheet.set_column(6, 6, 12)
        sheet.set_column(7, 7, 15)
        sheet.set_column(8, 8, 25)

        row = 1
        for transfer in transfers:
            for move in transfer.move_ids:
                sheet.write(row, 0, transfer.name or '', normal)
                sheet.write(row, 1, str(transfer.scheduled_date or ''), normal)
                sheet.write(row, 2, transfer.location_id.display_name or '', normal)
                sheet.write(row, 3, move.product_id.default_code or '', normal)
                sheet.write(row, 4, move.product_id.name or '', normal)
                sheet.write(row, 5, move.product_uom.name or '', normal)
                sheet.write(row, 6, move.product_uom_qty or 0, normal)
                sheet.write(row, 7, getattr(transfer, 'reason_code', False) and f'{transfer.reason_code.code}{transfer.reason_code.remark}' or '', normal)
                sheet.write(row, 8, transfer.location_dest_id.display_name or '', normal)
                row += 1

        workbook.close()
        output.seek(0)

        file_data = base64.b64encode(output.read())
        output.close()

        formatted_date = datetime.now().strftime('%d-%m-%Y')
        attachment = self.env['ir.attachment'].create({
            'name': f"Shop to shop transfer Report {formatted_date}.xlsx",
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


