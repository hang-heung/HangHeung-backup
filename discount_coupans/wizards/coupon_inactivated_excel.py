from odoo import models, fields, _
import base64
import io
import xlsxwriter


class CouponInactivatedExcelWizard(models.TransientModel):
    _name = 'coupon.inactivated.excel.wizard'
    _description = 'Inactivated Coupon Excel Wizard'

    from_date = fields.Date('From Date')
    to_date = fields.Date('To Date')
    file_data = fields.Binary('Excel File', readonly=True)
    file_name = fields.Char('File Name', readonly=True)

    def action_generate_excel(self):
        """Aggregate inactivated coupons by allocated store and program,
        and export three columns: Store Name | Coupon Name | amount of
        tickets. Coupons with no allocated_store_id appear under
        '(Unallocated)'."""
        domain = [
            ('status', '=', 'not_activated'),
            ('program_id.program_type', '=', 'coupons'),
        ]
        if self.from_date:
            domain.append(('create_date', '>=', self.from_date))
        if self.to_date:
            domain.append(('create_date', '<=', self.to_date))

        groups = self.env['loyalty.card'].read_group(
            domain,
            fields=['allocated_store_id', 'program_id'],
            groupby=['allocated_store_id', 'program_id'],
            lazy=False,
        )
        unallocated_label = _('(Unallocated)')

        rows = []
        for g in groups:
            store = g['allocated_store_id']
            store_name = store[1] if store else unallocated_label
            program = g['program_id']
            program_name = program[1] if program else ''
            rows.append((store_name, program_name, g['__count']))
        rows.sort(key=lambda r: (r[0], r[1]))

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Inactivated Coupons')

        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#F4CCCC',
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
        })
        cell_format = workbook.add_format({'valign': 'top', 'border': 1})
        int_format = workbook.add_format({
            'valign': 'top', 'border': 1, 'align': 'right',
            'num_format': '#,##0',
        })
        total_label_format = workbook.add_format({
            'bold': True, 'bg_color': '#FFF2CC', 'border': 1, 'align': 'left',
        })
        total_int_format = workbook.add_format({
            'bold': True, 'bg_color': '#FFF2CC', 'border': 1, 'align': 'right',
            'num_format': '#,##0',
        })

        headers = ['Store Name', 'Coupon Name', 'Amount of Tickets']
        sheet.set_column(0, 0, 30, cell_format)
        sheet.set_column(1, 1, 40, cell_format)
        sheet.set_column(2, 2, 22, int_format)

        for col, head in enumerate(headers):
            sheet.write(0, col, head, header_format)

        grand_total = 0
        for r_idx, (store_name, program_name, count) in enumerate(rows, start=1):
            sheet.write(r_idx, 0, store_name, cell_format)
            sheet.write(r_idx, 1, program_name, cell_format)
            sheet.write_number(r_idx, 2, int(count), int_format)
            grand_total += int(count)

        total_row = len(rows) + 1
        sheet.merge_range(total_row, 0, total_row, 1, 'Grand Total', total_label_format)
        sheet.write_number(total_row, 2, grand_total, total_int_format)

        workbook.close()
        output.seek(0)
        excel_data = output.read()

        date_from_str = self.from_date.strftime('%d-%m-%Y') if self.from_date else 'all'
        date_to_str = self.to_date.strftime('%d-%m-%Y') if self.to_date else 'all'
        self.write({
            'file_data': base64.b64encode(excel_data),
            'file_name': f"Coupon Made (Inactivated)_{date_from_str}-{date_to_str}.xlsx",
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f"/web/content/?model={self._name}&id={self.id}&field=file_data&filename_field=file_name&download=true",
            'target': 'self',
        }
