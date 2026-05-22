# -*- coding: utf-8 -*-
from odoo import models, fields, api
from datetime import datetime, time
import pytz
from io import BytesIO
import base64
import xlsxwriter

class ReceiptReasonReportWizard(models.TransientModel):
    _name = "receipt.reason.report.wizard"
    _description = "Receipt Reason Wise Report"

    start_date = fields.Date("Start Date", required=True)
    end_date = fields.Date("End Date", required=True)
    reason_code_ids = fields.Many2many(
        'reason.code',
        string="Reason Codes"
    )

    def action_generate_report(self):
        tz = pytz.timezone(self.env.user.tz or 'UTC')
        start_utc = tz.localize(datetime.combine(self.start_date, time.min)).astimezone(pytz.UTC)
        end_utc = tz.localize(datetime.combine(self.end_date, time.max)).astimezone(pytz.UTC)
        domain = [
            ('picking_type_code', 'in', ['incoming', 'internal', 'outgoing']),
            ('scheduled_date', '>=', start_utc.strftime('%Y-%m-%d %H:%M:%S')),
            ('scheduled_date', '<=', end_utc.strftime('%Y-%m-%d %H:%M:%S')),
        ]
        if self.reason_code_ids:
            domain.append(('reason_code', 'in', self.reason_code_ids.ids))
        else:
            domain.append(('reason_code', '!=', False))

        pickings = self.env['stock.picking'].sudo().search(domain)

        file_data = BytesIO()
        workbook = xlsxwriter.Workbook(file_data)
        sheet = workbook.add_worksheet("Receipt Report")

        # Header style
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#DCE6F1'
        })

        # Headers list
        headers = [
            'Picking Number',
            'Scheduled Date',
            'Partner',
            'Source Document',
            'Reason Code',
            'Product',
            'Demand Quantity',
            'Done Quantity',
            'UoM'
        ]

        # Fixed column widths (adjust as needed)
        column_widths = [20, 15, 25, 20, 15, 40, 15, 15, 10]

        # Write headers + apply widths
        for col, head in enumerate(headers):
            sheet.write(0, col, head, header_format)
            sheet.set_column(col, col, column_widths[col])

        row = 1

        # Fill Excel rows
        for picking in pickings:
            for line in picking.move_line_ids:

                move = line.move_id
                sheet.write(row, 0, picking.name or "")
                sheet.write(row, 1, str(picking.scheduled_date.date()) if picking.scheduled_date else "")
                sheet.write(row, 2, picking.partner_id.name or "")
                sheet.write(row, 3, picking.origin or "")
                rc = picking.reason_code
                sheet.write(row, 4, f'{rc.code} {rc.remark}' if rc else '')
                sheet.write(row, 5, line.product_id.display_name)
                sheet.write(row, 6, move.product_uom_qty)
                sheet.write(row, 7, line.qty_done)
                sheet.write(row, 8, line.product_uom_id.name)

                row += 1

        workbook.close()
        file_data.seek(0)

        # Create attachment
        attachment = self.env['ir.attachment'].create({
            'name': 'receipt_reason_report.xlsx',
            'type': 'binary',
            'datas': base64.b64encode(file_data.read()),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        })

        # Return download action
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }
