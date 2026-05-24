from odoo import models, fields, api
import io
import base64
from odoo.tools.misc import xlsxwriter
from odoo.exceptions import UserError
import csv

class ReportInventoryWizard(models.TransientModel):
    _name = 'report.inventory.wizard'
    _description = 'Inventory Report Wizard'

    start_date = fields.Date(string="Start Date", required=True)
    end_date = fields.Date(string="End Date", required=True)
    partner_id = fields.Many2one('res.partner', string="Shop")

    def print_report(self):
        if self.start_date > self.end_date:
            raise UserError("Start Date cannot be after End Date.")

        pickings = self.env['stock.picking'].search([
            ('scheduled_date', '>=', self.start_date),
            ('scheduled_date', '<=', self.end_date),
            ('state', 'in', ['draft', 'confirmed', 'assigned', 'done']),
            ('picking_type_id.code', '=', 'outgoing')
        ])

        if not pickings:
            raise UserError("No delivery records found in this date range.")

        def extract_code(name):
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

        product_set = set()
        report_data = {}
        product_uom_map = {}
        product_ref_map = {}

        if self.partner_id:
            partner_names = [extract_code(self.partner_id.name)]
        else:
            partner_names = sorted(
                set(extract_code(p.partner_id.name) for p in pickings if p.partner_id and p.partner_id.name)
            )

        for picking in pickings:
            partner_name = picking.partner_id.name
            if not partner_name:
                continue

            partner_code = extract_code(partner_name)

            for move in picking.move_ids_without_package:
                product = move.product_id
                item_code = product.old_item_number or ''
                product_name = product.name or 'Unknown'
                uom = move.product_uom.name or ''
                category = product.categ_id.name or 'Uncategorized'
                product_key = (category, item_code, product_name)

                product_set.add(product_key)
                product_uom_map[product_key] = uom
                product_ref_map[product_key] = product.default_code or ''
                report_data.setdefault(product_key, {}).setdefault(partner_code, 0)
                report_data[product_key][partner_code] += move.product_uom_qty

        sorted_products = sorted(product_set)

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Delivery Report')

        date_format = workbook.add_format({'bold': True, 'align': 'centre'})
        sheet.write(0, 0, f"Start Date: {self.start_date}", date_format)
        sheet.write(0, 2, f"End Date: {self.end_date}", date_format)

        sheet.set_column(0, 0, 30)  # Category
        sheet.set_column(1, 1, 20)  # Item Code
        sheet.set_column(2, 2, 20)  # Odoo Code
        sheet.set_column(3, 3, 40)  # Item Name
        sheet.set_column(4, 4, 10)  # UNIT
        for i in range(5, 5 + len(partner_names)):
            sheet.set_column(i, i, 20)

        header_format = workbook.add_format({'bold': True, 'align': 'center'})

        sheet.write(0, 0, '')  # Category
        sheet.write(0, 1, '')  # Item Code
        sheet.write(0, 2, '')  # Odoo Code
        sheet.write(0, 3, '')  # Item Name
        sheet.write(0, 4, '', header_format)  # UNIT
        for col, partner in enumerate(partner_names, start=5):
            sheet.write(0, col, partner, header_format)

        sheet.write(1, 0, 'Category', header_format)
        sheet.write(1, 1, 'Item Code', header_format)
        sheet.write(1, 2, 'Odoo Code', header_format)
        sheet.write(1, 3, 'Item Name', header_format)
        sheet.write(1, 4, 'UNIT', header_format)
        for col in range(5, 5 + len(partner_names)):
            sheet.write(1, col, 'UNIT', header_format)

        total_by_partner = {partner: 0 for partner in partner_names}
        row = 2

        for category, item_code, product_name in sorted_products:
            uom = product_uom_map.get((category, item_code, product_name), '')
            odoo_code = product_ref_map.get((category, item_code, product_name), '')
            sheet.write(row, 0, category)
            sheet.write(row, 1, item_code)
            sheet.write(row, 2, odoo_code)
            sheet.write(row, 3, product_name)
            sheet.write(row, 4, uom)

            for col, partner in enumerate(partner_names, start=5):
                qty = report_data.get((category, item_code, product_name), {}).get(partner, 0)
                sheet.write(row, col, qty)
                total_by_partner[partner] += qty

            row += 1

        sheet.write(row, 4, 'Total', header_format)
        for col, partner in enumerate(partner_names, start=5):
            sheet.write(row, col, total_by_partner[partner], header_format)

        workbook.close()
        output.seek(0)
        xlsx_data = output.read()
        output.close()

        attachment = self.env['ir.attachment'].create({
            'name': 'Pickup Slip Summary.xlsx',
            'type': 'binary',
            'datas': base64.b64encode(xlsx_data),
            'res_model': 'report.inventory.wizard',
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        })

        download_url = f'/web/content/{attachment.id}?download=true'
        return {
            'type': 'ir.actions.act_url',
            'url': download_url,
            'target': 'self',
        }

    def print_csv_report(self):
        if self.start_date > self.end_date:
            raise UserError("Start Date cannot be after End Date.")

        pickings = self.env['stock.picking'].search([
            ('scheduled_date', '>=', self.start_date),
            ('scheduled_date', '<=', self.end_date),
            ('state', 'in', ['draft', 'confirmed', 'assigned']),
            ('picking_type_id.code', '=', 'outgoing')
        ])

        if not pickings:
            raise UserError("No delivery records found in this date range.")

        def extract_code(name):
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

        product_set = set()
        report_data = {}

        if self.partner_id:
            partner_names = [extract_code(self.partner_id.name)]
        else:
            partner_names = sorted(
                set(extract_code(p.partner_id.name) for p in pickings if p.partner_id and p.partner_id.name)
            )

        for picking in pickings:
            partner_name = picking.partner_id.name
            if not partner_name:
                continue

            partner_code = extract_code(partner_name)

            for move in picking.move_ids_without_package:
                product = move.product_id
                item_code = product.old_item_number or ''
                product_name = product.name or 'Unknown'
                product_key = (item_code, product_name)

                product_set.add(product_key)
                report_data.setdefault(product_key, {}).setdefault(partner_code, 0)
                report_data[product_key][partner_code] += move.product_uom_qty

        sorted_products = sorted(product_set)

        output = io.StringIO()
        writer = csv.writer(output)

        # Header row: only Item Code + partner columns
        header = ['Item Code'] + partner_names
        writer.writerow(header)

        total_by_partner = {partner: 0 for partner in partner_names}

        for item_code, product_name in sorted_products:
            row = [item_code]

            for partner in partner_names:
                qty = report_data.get((item_code, product_name), {}).get(partner, 0)
                row.append(int(qty))
                total_by_partner[partner] += qty

            writer.writerow(row)

        # Total row
        total_row = ['Grand Total'] + [int(total_by_partner[partner]) for partner in partner_names]
        writer.writerow(total_row)

        csv_data = output.getvalue().encode('utf-8-sig')  # BOM Chinese
        output.close()

        attachment = self.env['ir.attachment'].create({
            'name': 'Pickup Slip Summary.csv',
            'type': 'binary',
            'datas': base64.b64encode(csv_data),
            'res_model': 'report.inventory.wizard',
            'res_id': self.id,
            'mimetype': 'text/csv'
        })

        download_url = f'/web/content/{attachment.id}?download=true'
        return {
            'type': 'ir.actions.act_url',
            'url': download_url,
            'target': 'self',
        }
