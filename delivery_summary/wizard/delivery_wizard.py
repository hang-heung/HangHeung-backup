# -*- coding: utf-8 -*-
from odoo import models, fields, api
import io
import base64
from odoo.tools.misc import xlsxwriter
from odoo.exceptions import UserError


class ReportDeliveryWizard(models.TransientModel):
    _name = 'report.delivery.wizard'
    _description = 'Delivery Summary Report Wizard'

    start_date = fields.Date(string="Start Date", required=True)
    end_date = fields.Date(string="End Date", required=True)
    partner_id = fields.Many2one('res.partner', string="Shop")

    def _extract_code(self, name):
        """Extract short shop code from partner name, same logic as pickup_slip_summary."""
        if ',' in name and '-' in name:
            try:
                return name.split(',')[1].split('-')[0].strip()
            except IndexError:
                return name.strip()
        elif '-' in name:
            try:
                return name.split('-')[0].strip()
            except IndexError:
                return name.strip()
        return name.strip()

    def print_report(self):
        if self.start_date > self.end_date:
            raise UserError("Start Date cannot be after End Date.")

        # Use done pickings only — we want actual delivered qty (ml.quantity)
        pickings = self.env['stock.picking'].search([
            ('scheduled_date', '>=', self.start_date),
            ('scheduled_date', '<=', self.end_date),
            ('state', '=', 'done'),
            ('picking_type_id.code', '=', 'outgoing'),
        ])

        if not pickings:
            raise UserError("No completed delivery records found in this date range.")

        product_set = set()
        report_data = {}
        product_uom_map = {}
        product_ref_map = {}

        if self.partner_id:
            partner_names = [self._extract_code(self.partner_id.name)]
        else:
            partner_names = sorted(
                set(
                    self._extract_code(p.partner_id.name)
                    for p in pickings
                    if p.partner_id and p.partner_id.name
                )
            )

        for picking in pickings:
            if not picking.partner_id or not picking.partner_id.name:
                continue
            partner_code = self._extract_code(picking.partner_id.name)
            if self.partner_id and partner_code != partner_names[0]:
                continue

            for ml in picking.move_line_ids:
                if ml.quantity <= 0:
                    continue
                product = ml.product_id
                item_code = product.old_item_number or ''
                product_name = product.name or 'Unknown'
                uom = ml.product_uom_id.name or ''
                category = product.categ_id.name or 'Uncategorized'
                product_key = (category, item_code, product_name)

                product_set.add(product_key)
                product_uom_map[product_key] = uom
                product_ref_map[product_key] = product.default_code or ''
                report_data.setdefault(product_key, {}).setdefault(partner_code, 0)
                report_data[product_key][partner_code] += ml.quantity

        if not product_set:
            raise UserError("No delivered quantities found for the selected criteria.")

        sorted_products = sorted(product_set)

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Delivery Summary')

        # Formats
        header_format = workbook.add_format({'bold': True, 'align': 'center', 'bg_color': '#AF8489', 'font_color': '#FFFFFF', 'border': 1})
        title_format = workbook.add_format({'bold': True})
        number_format = workbook.add_format({'num_format': '#,##0', 'border': 1})
        text_format = workbook.add_format({'border': 1})
        total_format = workbook.add_format({'bold': True, 'num_format': '#,##0', 'border': 1, 'bg_color': '#F2DCDB'})
        total_label_format = workbook.add_format({'bold': True, 'border': 1, 'bg_color': '#F2DCDB'})

        # Title row
        sheet.write(0, 0, f"Delivery Summary", title_format)
        sheet.write(0, 2, f"Start Date: {self.start_date}", title_format)
        sheet.write(0, 4, f"End Date: {self.end_date}", title_format)

        total_col = 5 + len(partner_names)  # last column index for row total

        # Column widths
        sheet.set_column(0, 0, 20)   # Category
        sheet.set_column(1, 1, 18)   # Item Code
        sheet.set_column(2, 2, 18)   # Odoo Code
        sheet.set_column(3, 3, 40)   # Item Name
        sheet.set_column(4, 4, 10)   # Unit
        for i in range(5, total_col):
            sheet.set_column(i, i, 14)
        sheet.set_column(total_col, total_col, 14)  # Total column

        # Header row
        sheet.write(1, 0, 'Category', header_format)
        sheet.write(1, 1, 'Item Code', header_format)
        sheet.write(1, 2, 'Odoo Code', header_format)
        sheet.write(1, 3, 'Item Name', header_format)
        sheet.write(1, 4, 'Unit', header_format)
        for col, partner in enumerate(partner_names, start=5):
            sheet.write(1, col, partner, header_format)
        sheet.write(1, total_col, 'Total', header_format)

        # Data rows
        total_by_partner = {partner: 0 for partner in partner_names}
        grand_total = 0
        row = 2

        for category, item_code, product_name in sorted_products:
            uom = product_uom_map.get((category, item_code, product_name), '')
            odoo_code = product_ref_map.get((category, item_code, product_name), '')
            sheet.write(row, 0, category, text_format)
            sheet.write(row, 1, item_code, text_format)
            sheet.write(row, 2, odoo_code, text_format)
            sheet.write(row, 3, product_name, text_format)
            sheet.write(row, 4, uom, text_format)

            row_total = 0
            for col, partner in enumerate(partner_names, start=5):
                qty = report_data.get((category, item_code, product_name), {}).get(partner, 0)
                if qty:
                    sheet.write(row, col, qty, number_format)
                    total_by_partner[partner] += qty
                    row_total += qty
                else:
                    sheet.write_blank(row, col, None, number_format)
            sheet.write(row, total_col, row_total if row_total else None, number_format)
            grand_total += row_total

            row += 1

        # Total row
        sheet.write(row, 3, 'Grand Total', total_label_format)
        sheet.write(row, 4, '', total_label_format)
        for col, partner in enumerate(partner_names, start=5):
            sheet.write(row, col, total_by_partner[partner], total_format)
        sheet.write(row, total_col, grand_total, total_format)

        workbook.close()
        output.seek(0)
        xlsx_data = output.read()
        output.close()

        attachment = self.env['ir.attachment'].create({
            'name': f'Delivery Summary {self.start_date} to {self.end_date}.xlsx',
            'type': 'binary',
            'datas': base64.b64encode(xlsx_data),
            'res_model': 'report.delivery.wizard',
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }
