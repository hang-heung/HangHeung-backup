from odoo import models, fields, api, _
from datetime import datetime,time
import base64
import io
import xlsxwriter
from odoo.exceptions import ValidationError
import pytz

class CouponGiftVoucherExcelWizard(models.TransientModel):
    _name = 'coupon.gift.voucher.report.wizard'
    _description = 'Coupon Gift Voucher Excel Report'

    date_start = fields.Date(string='Start Date', required=True)
    date_end = fields.Date(string='End Date', required=True)
    file_data = fields.Binary('Excel File', readonly=True)
    file_name = fields.Char('File Name', readonly=True)

    @api.constrains('date_start', 'date_end')
    def _check_date_range(self):
        for record in self:
            if record.date_start and record.date_end and record.date_end < record.date_start:
                raise ValidationError("End Date cannot be earlier than Start Date.")

    def action_generate_excel(self):

        user_tz = pytz.timezone(self.env.user.tz or 'UTC')

        # Build datetimes in user timezone
        start_dt_user = datetime.combine(self.date_start, time.min)
        end_dt_user   = datetime.combine(self.date_end, time.max)

        # Localize to user TZ and convert to UTC (what Odoo stores in DB)
        start_datetime = user_tz.localize(start_dt_user).astimezone(pytz.UTC)
        end_datetime = user_tz.localize(end_dt_user).astimezone(pytz.UTC)

        domain = [
            ('status', 'in', ['activated', 'redeemed']),
            ('program_id.program_type', '=', 'coupons'),
            ('history_ids.create_date', '>=', start_datetime),
            ('history_ids.create_date', '<=', end_datetime),
        ]
        redeemed_coupons_records = self.env['loyalty.card'].search(domain + [
            ('history_ids.order_id', '!=', False),
        ])

        sold_coupons_records = self.env['loyalty.card'].search(domain + [
            ('id', 'not in', redeemed_coupons_records.ids),
            ('history_ids.order_id', '=', False),
        ])

        pos_coupons_records = redeemed_coupons_records | sold_coupons_records
        if not pos_coupons_records:
            raise ValidationError(_("No records found in this date range."))

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Coupons Gift Voucher')

        header_format = workbook.add_format({
            'bold': True,
            # 'bg_color': "#9394C5",
            'align': 'center',
            'valign': 'vcenter'
        })
        bold_left_txt_format = workbook.add_format({
            'bold': True,
            'align': 'left',
            'valign': 'vcenter'
        })
        bold_right_txt_format = workbook.add_format({
            'bold': True,
            'align': 'right',
            'valign': 'vcenter'
        })
        cell_format = workbook.add_format({'text_wrap': True, 'valign': 'center', 'align': 'left'})
        cell_right_format = workbook.add_format({'text_wrap': True, 'valign': 'center', 'align': 'right'})

        pos_coupons_stores = sold_coupons_records.mapped('allocated_store_id') | redeemed_coupons_records.mapped('redeem_shop_id')
        product_records = pos_coupons_records.mapped('program_id').mapped('product_id')

        sheet.set_column(0, 0, 15, cell_format)
        sheet.set_column(1, 1, 15, cell_format)
        sheet.set_column(2, 2, 25, cell_format)
        sheet.set_column(3, 3, 15, cell_format)
        sheet.set_column(4, 4, 15, cell_format)


        sheet.merge_range(0, 0, 0, 3, self.env.company.name if self.env.company else '', bold_left_txt_format)
        sheet.merge_range(1, 0, 1, 3, '禮券銷售及兌換報表', bold_left_txt_format)
        sheet.merge_range(2, 0, 2, 3, '%s to %s'%(self.date_start.strftime("%d/%m/%y"), self.date_end.strftime("%d/%m/%y")), bold_left_txt_format)


        ##  Redeemed and Sold Label
        row = 4
        col = 2
        len_of_store = len(pos_coupons_stores)
        redeemed_colspan = col + len_of_store
        # sheet.merge_range(row, col, row, redeemed_colspan, 'Redeemed', header_format)
        sheet.merge_range(row, col, row, redeemed_colspan, '已兌換', header_format)
        col = redeemed_colspan + 1
        sold_colspan = col + len_of_store
        # sheet.merge_range(row, col, row, sold_colspan, 'Sold', header_format)
        sheet.merge_range(row, col, row, sold_colspan, '已賣', header_format)
        col = redeemed_colspan + 1 + sold_colspan
        for col_format in range(2, col+1):
            sheet.set_column(row, col_format, 25, cell_format)

        ## Stores Names
        row += 1
        col = 2
        sold_col = col + len_of_store + 1
        for store_name in pos_coupons_stores.mapped('name'):
            sheet.write(row, col, store_name, header_format)
            sheet.write(row, sold_col, store_name, header_format)
            col += 1
            sold_col += 1
        sheet.write(row, col, "Sum Of QTY", header_format)
        sheet.write(row, sold_col, "Sum Of QTY", header_format)
        sold_col += 1
        sheet.write(row, sold_col, "Total Sum Of QTY", header_format)

        ## Set Headers
        col = 0
        row += 1
        sheet.write(row, col, "Item Code", header_format)
        col += 1
        sheet.write(row, col, "Item Name", header_format)
        col += 1
        sold_col = col + len_of_store + 1
        for store_name in pos_coupons_stores:
            sheet.write(row, col, "QTY", header_format)
            sheet.write(row, sold_col, "QTY", header_format)
            col += 1
            sold_col += 1
        sheet.write(row, col, "", header_format)
        sheet.write(row, sold_col, "", header_format)
        sold_col += 1
        sheet.write(row, sold_col, "", header_format)

        ## Set Dynamic Data
        row += 1
        grand_total_qty_dict = {}
        for product in product_records:
            col = 0
            sheet.write(row, col, product.default_code or '', cell_format)
            col += 1
            sheet.write(row, col, product.name or '', cell_format)
            col += 1
            sold_col = col + len_of_store + 1
            total_redeemed_qty = total_sold_qty = 0
            for store_id in pos_coupons_stores:
                # loyalty_coupons_records = pos_coupons_records.filtered(lambda ln: ln.program_id.product_id.id == product.id)
                # redeemed_qty = len(loyalty_coupons_records.filtered(lambda ln: ln.status == "redeemed"))
                # sold_qty = len(loyalty_coupons_records.filtered(lambda ln: ln.status == "activated"))
                redeemed_qty = len(redeemed_coupons_records.filtered(lambda ln: ln.program_id.product_id.id == product.id and ln.redeem_shop_id.id == store_id.id))
                sold_qty = len(sold_coupons_records.filtered(lambda ln: ln.program_id.product_id.id == product.id and ln.allocated_store_id.id == store_id.id))
                # sold_qty = len(loyalty_coupons_records.filtered(lambda ln: ln.status == "activated"))

                sheet.write(row, col, redeemed_qty, cell_right_format)
                total_redeemed_qty += redeemed_qty
                gt_redeemed_qty = grand_total_qty_dict.get(str(store_id.id)).get('redeemed_qty', 0) + redeemed_qty if grand_total_qty_dict.get(str(store_id.id)) else redeemed_qty
                sheet.write(row, sold_col, sold_qty, cell_right_format)
                total_sold_qty += sold_qty
                gt_sold_qty = grand_total_qty_dict.get(str(store_id.id)).get('sold_qty', 0) + sold_qty if grand_total_qty_dict.get(str(store_id.id)) else sold_qty
                grand_total_qty_dict[str(store_id.id)] = {'redeemed_qty' : gt_redeemed_qty, 'sold_qty' : gt_sold_qty}

                col += 1
                sold_col += 1
            sheet.write(row, col, total_redeemed_qty, bold_right_txt_format)
            sheet.write(row, sold_col, total_sold_qty, bold_right_txt_format)
            sold_col += 1
            sheet.write(row, sold_col, total_redeemed_qty + total_sold_qty, bold_right_txt_format)
            row += 1

        row += 1
        col = 0
        sheet.write(row, col, "Grand Total", bold_left_txt_format)
        col = 2
        sold_col = col + len_of_store + 1
        grand_total_redeemed_qty = grand_total_sold_qty = 0
        for gt_rec in pos_coupons_stores:
            grand_redeemed_qty = grand_total_qty_dict.get(str(gt_rec.id)).get('redeemed_qty', 0) if grand_total_qty_dict.get(str(gt_rec.id)) else 0
            grand_total_redeemed_qty += grand_redeemed_qty
            grand_sold_qty = grand_total_qty_dict.get(str(gt_rec.id)).get('sold_qty', 0) if grand_total_qty_dict.get(str(gt_rec.id)) else 0
            grand_total_sold_qty += grand_sold_qty

            sheet.write(row, col, grand_redeemed_qty, bold_right_txt_format)
            sheet.write(row, sold_col, grand_sold_qty, bold_right_txt_format)
            col += 1
            sold_col += 1
        sheet.write(row, col, grand_total_redeemed_qty, bold_right_txt_format)
        sheet.write(row, sold_col, grand_total_sold_qty, bold_right_txt_format)
        sold_col += 1
        sheet.write(row, sold_col, grand_total_redeemed_qty+grand_total_sold_qty, bold_right_txt_format)


        workbook.close()
        output.seek(0)
        excel_data = output.read()

        self.write({
            'file_data': base64.b64encode(excel_data),
            'file_name': f"禮券銷售及兌換報表 {self.date_start.strftime('%Y-%m-%d')} 至 {self.date_end.strftime('%Y-%m-%d')}.xlsx",
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f"/web/content/?model={self._name}&id={self.id}&field=file_data&filename_field=file_name&download=true",
            'target': 'self',
        }
