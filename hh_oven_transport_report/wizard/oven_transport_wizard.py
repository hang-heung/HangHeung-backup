# -*- coding: utf-8 -*-
import io
import re
import math
import base64

from odoo import models, fields, api
from odoo.tools.misc import xlsxwriter
from odoo.exceptions import UserError


class OvenTransportWizard(models.TransientModel):
    _name = 'oven.transport.wizard'
    _description = '燒爐及運輸執貨紙 Wizard'

    start_date  = fields.Date(string="Start Date", required=True)
    end_date    = fields.Date(string="End Date", required=True)
    partner_ids = fields.Many2many(
        'res.partner', string="Shops",
        domain=[('type', '=', 'delivery')],
    )
    report_type = fields.Selection([
        ('demand',   '需求 Demand'),
        ('delivery', '送貨 Delivery'),
    ], string="Type", required=True, default='delivery')

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_code(name):
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

    @staticmethod
    def _packing_number(spec):
        if not spec:
            return None
        m = re.search(r'\d+', spec)
        return int(m.group()) if m else None

    @staticmethod
    def _is_six_piece(name):
        return bool(name) and '6件' in name

    @staticmethod
    def _extract_display_name(name):
        """Return the part of the partner name after the first '-'."""
        if '-' in name:
            after = name.split('-', 1)[1].strip()
            return after if after else name.strip()
        return name.strip()

    def _warehouse_display_map(self):
        """Build {shop_code: display_name} from stock.warehouse names.

        Warehouse names follow the pattern  "CODE - 名稱"  (e.g. "AB1 - 香港仔").
        The part before ' - ' is used as the lookup key; the part after is the
        human-readable column title.  To update a title, just rename the
        warehouse in Inventory → Configuration → Warehouses — no code change needed.
        """
        mapping = {}
        for wh in self.env['stock.warehouse'].sudo().search([]):
            if ' - ' in wh.name:
                code_part, display = wh.name.split(' - ', 1)
                mapping[code_part.strip()] = display.strip()
        return mapping

    def _suanbing_category_ids(self):
        Category = self.env['product.category']
        categ = Category.search([('complete_name', '=', 'H01 酥餅')], limit=1)
        if not categ:
            categ = Category.search([('name', '=', '酥餅')], limit=1)
        if not categ:
            raise UserError("Cannot find the H01 酥餅 product category.")
        return Category.search([('id', 'child_of', categ.id)]).ids

    def _collect(self):
        """Aggregate outgoing picking quantities for H01 酥餅 products.

        Returns (partner_codes, products, data, code_display) where:
          partner_codes : ordered list of shop codes  (internal key)
          products      : 6件 products first, then 1件 sorted by item code
          data          : {product_id: {partner_code: raw_qty}}
          code_display  : {partner_code: display_name_after_dash}
        """
        if self.start_date > self.end_date:
            raise UserError("Start Date cannot be after End Date.")

        # Demand = planned qty from all active pickings (Pick Slip Summary logic)
        # Delivery = actual qty from validated pickings only (Delivery Summary logic)
        is_demand = self.report_type == 'demand'
        state_filter = ('state', 'in', ['draft', 'confirmed', 'assigned', 'done']) \
                       if is_demand else ('state', '=', 'done')
        pickings = self.env['stock.picking'].search([
            ('scheduled_date', '>=', self.start_date),
            ('scheduled_date', '<=', self.end_date),
            state_filter,
            ('picking_type_id.code', '=', 'outgoing'),
        ])
        if not pickings:
            err = "No demand records" if is_demand else "No completed delivery records"
            raise UserError("%s found in this date range." % err)

        categ_ids = set(self._suanbing_category_ids())

        # Build allowed partner code set; empty = all shops
        if self.partner_ids:
            allowed_codes = {self._extract_code(p.name) for p in self.partner_ids}
            partner_codes = sorted(allowed_codes)
        else:
            allowed_codes = None  # no filter
            partner_codes = sorted(set(
                self._extract_code(p.partner_id.name)
                for p in pickings if p.partner_id and p.partner_id.name
            ))

        product_info = {}
        data = {}
        code_display = {}   # {shop_code: display_name_after_dash}
        for picking in pickings:
            if not picking.partner_id or not picking.partner_id.name:
                continue
            pname = picking.partner_id.name
            code  = self._extract_code(pname)
            if allowed_codes is not None and code not in allowed_codes:
                continue
            if code not in code_display:
                code_display[code] = self._extract_display_name(pname)
            if is_demand:
                # Demand: planned qty from stock moves
                for move in picking.move_ids_without_package:
                    if move.product_uom_qty <= 0:
                        continue
                    product = move.product_id
                    if product.categ_id.id not in categ_ids:
                        continue
                    key = product.id
                    if key not in product_info:
                        product_info[key] = {
                            'item_code': product.old_item_number or '',
                            'odoo_code': product.default_code or '',
                            'name': product.name or '',
                            'spec': product.packing_spec or '',
                        }
                    data.setdefault(key, {}).setdefault(code, 0.0)
                    data[key][code] += move.product_uom_qty
            else:
                # Delivery: actual qty from move lines
                for ml in picking.move_line_ids:
                    if ml.quantity <= 0:
                        continue
                    product = ml.product_id
                    if product.categ_id.id not in categ_ids:
                        continue
                    key = product.id
                    if key not in product_info:
                        product_info[key] = {
                            'item_code': product.old_item_number or '',
                            'odoo_code': product.default_code or '',
                            'name': product.name or '',
                            'spec': product.packing_spec or '',
                        }
                    data.setdefault(key, {}).setdefault(code, 0.0)
                    data[key][code] += ml.quantity

        all_products = [
            dict(product_info[k], key=k)
            for k in product_info
            if any(data.get(k, {}).values())
        ]
        six = sorted(
            [p for p in all_products if self._is_six_piece(p['name'])],
            key=lambda p: (p['item_code'], p['name'])
        )
        ones = sorted(
            [p for p in all_products if not self._is_six_piece(p['name'])],
            key=lambda p: (p['item_code'], p['name'])
        )
        return partner_codes, six + ones, data, code_display

    def _cell_value(self, product, raw_qty):
        """Divided qty (運輸執貨紙) or pan count (燒爐紙). (6件) kept raw.
        Division result is ceiling-rounded (e.g. 1.2 → 2), 0 stays 0."""
        if not raw_qty:
            return 0
        if self._is_six_piece(product['name']):
            return raw_qty
        num = self._packing_number(product['spec'])
        if not num:
            return raw_qty
        return math.ceil(raw_qty / num)

    @staticmethod
    def _write_val(ws, row, col, val, fmt_int, fmt_dec):
        """Write a numeric value using int format for whole numbers, decimal format
        for fractional values, and a blank cell for zero."""
        if not val:
            ws.write_blank(row, col, None, fmt_int)
        elif val == int(val):
            ws.write(row, col, int(val), fmt_int)
        else:
            ws.write(row, col, val, fmt_dec)

    # ------------------------------------------------------------------
    # 運輸執貨紙
    # ------------------------------------------------------------------
    def print_transport_report(self):
        partner_codes, products, data, code_display = self._collect()
        wh_display = self._warehouse_display_map()   # {code: 名稱} from stock.warehouse

        output = io.BytesIO()
        wb = xlsxwriter.Workbook(output, {'in_memory': True})
        ws = wb.add_worksheet('運輸執貨紙')

        ws.set_landscape()
        ws.fit_to_pages(1, 0)
        ws.set_margins(left=0.25, right=0.25, top=0.5, bottom=0.5)
        ws.set_paper(9)  # A4

        bold_title = wb.add_format({'bold': True, 'font_size': 12})
        hdr = wb.add_format({'bold': True, 'align': 'center', 'border': 1,
                             'bg_color': '#D9E1F2', 'font_size': 9})
        cell_fmt = wb.add_format({'border': 1, 'font_size': 9})
        numf_int  = wb.add_format({'border': 1, 'font_size': 9})
        numf_dec  = wb.add_format({'border': 1, 'num_format': '0.##', 'font_size': 9})
        bold_int  = wb.add_format({'bold': True, 'border': 1, 'font_size': 9,
                                   'bg_color': '#D9E1F2', 'align': 'center'})
        bold_dec  = wb.add_format({'bold': True, 'border': 1, 'num_format': '0.##',
                                   'font_size': 9, 'bg_color': '#D9E1F2', 'align': 'center'})

        ws.write(0, 2, "運輸執貨紙", bold_title)
        ws.write(0, 3, "日期 : %s" % self.start_date, bold_title)

        ws.write(1, 0, 'Item Code', hdr)
        ws.write(1, 1, 'Odoo Code', hdr)
        ws.write(1, 2, 'Item Name', hdr)
        ws.write(1, 3, '包裝規格', hdr)
        for i, code in enumerate(partner_codes):
            ws.write(1, 4 + i, wh_display.get(code, code), hdr)
        total_col = 4 + len(partner_codes)
        ws.write(1, total_col, '總數', hdr)

        ws.set_column(0, 0, 10)
        ws.set_column(1, 1, 12)
        ws.set_column(2, 2, 22)
        ws.set_column(3, 3, 6)
        ws.set_column(4, total_col, 5)
        ws.set_row(1, 18)

        six_products = [p for p in products if self._is_six_piece(p['name'])]
        one_products = [p for p in products if not self._is_six_piece(p['name'])]

        # Divisor for 6件 subtotal: 包裝規格 of 老婆餅(6件)
        six_divisor = None
        for p in six_products:
            if '老婆餅' in p['name'] and '少甜' not in p['name']:
                six_divisor = self._packing_number(p['spec'])
                break
        if six_divisor is None and six_products:
            six_divisor = self._packing_number(six_products[0]['spec'])

        # Hardcoded divisor overrides: {(odoo_code, shop_code): divisor}
        # These override the packing_spec for specific product+shop combinations.
        DIVISOR_OVERRIDES = {
            ('H0100101000', 'TST'): 56,
            ('H0100101000', 'YLF'): 56,
        }

        col_totals = [0.0] * len(partner_codes)
        six_col_raws = [0.0] * len(partner_codes)
        row = 2

        for p in six_products:
            ws.write(row, 0, p['item_code'], cell_fmt)
            ws.write(row, 1, p['odoo_code'], cell_fmt)
            ws.write(row, 2, p['name'], cell_fmt)
            num = self._packing_number(p['spec'])
            ws.write(row, 3, num if num else (p['spec'] or ''), cell_fmt)
            row_total = 0.0
            for i, code in enumerate(partner_codes):
                raw = data.get(p['key'], {}).get(code, 0)
                val = self._cell_value(p, raw)
                six_col_raws[i] += raw
                self._write_val(ws, row, 4 + i, val, numf_int, numf_dec)
                col_totals[i] += val
                row_total += val
            self._write_val(ws, row, total_col, int(row_total), numf_int, numf_dec)
            row += 1

        # 6件 subtotal: sum of raw qtys ÷ 老婆餅(6件) 包裝規格
        if six_products and six_divisor:
            ws.write(row, 2, '總數', hdr)
            ws.write(row, 3, six_divisor, hdr)
            six_grand_raw = sum(six_col_raws)
            for i in range(len(partner_codes)):
                div_val = math.ceil(six_col_raws[i] / six_divisor) if six_col_raws[i] else 0
                self._write_val(ws, row, 4 + i, div_val, bold_int, bold_dec)
            grand_div = math.ceil(six_grand_raw / six_divisor) if six_grand_raw else 0
            self._write_val(ws, row, total_col, grand_div, bold_int, bold_dec)
            row += 1

        for p in one_products:
            ws.write(row, 0, p['item_code'], cell_fmt)
            ws.write(row, 1, p['odoo_code'], cell_fmt)
            ws.write(row, 2, p['name'], cell_fmt)
            num = self._packing_number(p['spec'])
            ws.write(row, 3, num if num else (p['spec'] or ''), cell_fmt)
            row_total = 0.0
            for i, code in enumerate(partner_codes):
                raw = data.get(p['key'], {}).get(code, 0)
                override_div = DIVISOR_OVERRIDES.get((p['odoo_code'], code))
                if override_div and raw:
                    val = math.ceil(raw / override_div)
                else:
                    val = self._cell_value(p, raw)
                self._write_val(ws, row, 4 + i, val, numf_int, numf_dec)
                col_totals[i] += val
                row_total += val
            self._write_val(ws, row, total_col, round(row_total, 2), numf_int, numf_dec)
            row += 1

        # Grand total row
        ws.write(row, 2, '總數', hdr)
        grand = 0.0
        for i in range(len(partner_codes)):
            v = round(col_totals[i], 2)
            self._write_val(ws, row, 4 + i, v, bold_int, bold_dec)
            grand += col_totals[i]
        self._write_val(ws, row, total_col, round(grand, 2), bold_int, bold_dec)

        wb.close()
        type_label = '需求' if self.report_type == 'demand' else '送貨'
        filename = '運輸紙_%s_%s.xlsx' % (type_label, self.start_date.strftime('%Y%m%d'))
        return self._download(output, filename)

    # ------------------------------------------------------------------
    # 燒爐紙
    # ------------------------------------------------------------------
    def print_oven_report(self):
        partner_codes, products, data, _code_display = self._collect()

        for p in products:
            p['grand_raw'] = sum(data.get(p['key'], {}).values())

        six  = [p for p in products if self._is_six_piece(p['name'])]
        ones = [p for p in products if not self._is_six_piece(p['name'])]

        output = io.BytesIO()
        wb = xlsxwriter.Workbook(output, {'in_memory': True})
        ws = wb.add_worksheet('燒爐紙')

        # Landscape, fit to one page wide, narrow margins
        ws.set_landscape()
        ws.fit_to_pages(1, 0)
        ws.set_margins(left=0.25, right=0.25, top=0.5, bottom=0.5)
        ws.set_paper(9)  # A4

        FS = 9

        # ── Formats ──────────────────────────────────────────────────────
        title_f   = wb.add_format({'bold': True, 'font_size': 11})
        date_f    = wb.add_format({'bold': True, 'font_size': FS})

        # Section header: dark blue bg, white bold text, bordered
        sec_hdr   = wb.add_format({'bold': True, 'font_color': '#FFFFFF',
                                   'bg_color': '#4472C4', 'border': 1,
                                   'align': 'center', 'font_size': FS})
        # Sub-section header (盆餅): lighter blue
        sub_hdr   = wb.add_format({'bold': True, 'font_color': '#FFFFFF',
                                   'bg_color': '#5B9BD5', 'border': 1,
                                   'align': 'center', 'font_size': FS})

        cell_f    = wb.add_format({'border': 1, 'font_size': FS})
        name_f    = wb.add_format({'border': 1, 'font_size': 14})
        numf_int  = wb.add_format({'border': 1, 'font_size': 16, 'bold': True, 'align': 'center'})
        numf_dec  = wb.add_format({'border': 1, 'num_format': '0.##',
                                   'font_size': 16, 'bold': True, 'align': 'center'})

        # ── Column layout per half (6 cols) ──────────────────────────────
        # b+0 : Odoo Code       (left sub-col)
        # b+1 : Item Name       (left sub-col)
        # b+2 : Left value      (6件 qty  OR  left 盆 count)
        # b+3 : Right Odoo Code (盆餅 section only)
        # b+4 : Right Name      (盆餅 section only)
        # b+5 : Right 盆 count  (盆餅 section only)
        # gap col between halves

        def set_cols(base):
            ws.set_column(base + 0, base + 0, 9)   # Odoo Code
            ws.set_column(base + 1, base + 1, 20)  # Item Name
            ws.set_column(base + 2, base + 2, 7)   # Left value
            ws.set_column(base + 3, base + 3, 9)   # Right Odoo Code
            ws.set_column(base + 4, base + 4, 20)  # Right Name
            ws.set_column(base + 5, base + 5, 7)   # Right value

        HALF = 6   # columns per half
        GAP  = 1   # gap column between the two halves

        set_cols(0)
        ws.set_column(HALF, HALF, 2)            # gap col
        set_cols(HALF + GAP)

        half_ones = (len(ones) + 1) // 2
        left_ones  = ones[:half_ones]
        right_ones = ones[half_ones:]

        def render(base):
            r = 0
            # ── Title / date row ─────────────────────────────────────────
            ws.write(r, base + 0, '燒爐紙', title_f)
            ws.write(r, base + 3, '日期 :', date_f)
            ws.write(r, base + 4, str(self.start_date), date_f)
            r += 1

            # ── 6件 section header ────────────────────────────────────────
            ws.write(r, base + 0, 'Odoo Code', sec_hdr)
            ws.write(r, base + 1, '品名',      sec_hdr)
            ws.write(r, base + 2, '數量',      sec_hdr)
            ws.write_blank(r, base + 3, None,  sec_hdr)
            ws.write_blank(r, base + 4, None,  sec_hdr)
            ws.write_blank(r, base + 5, None,  sec_hdr)
            r += 1

            # ── 6件 data rows ─────────────────────────────────────────────
            for p in six:
                ws.write(r, base + 0, p['odoo_code'], cell_f)
                ws.write(r, base + 1, p['name'],      name_f)
                self._write_val(ws, r, base + 2, p['grand_raw'], numf_int, numf_dec)
                ws.write_blank(r, base + 3, None, cell_f)
                ws.write_blank(r, base + 4, None, cell_f)
                ws.write_blank(r, base + 5, None, cell_f)
                r += 1

            r += 1  # spacer row (no border)

            # ── 盆餅 section header ───────────────────────────────────────
            ws.write(r, base + 0, 'Odoo Code', sub_hdr)
            ws.write(r, base + 1, '品名',      sub_hdr)
            ws.write(r, base + 2, '盆數',      sub_hdr)
            ws.write(r, base + 3, 'Odoo Code', sub_hdr)
            ws.write(r, base + 4, '品名',      sub_hdr)
            ws.write(r, base + 5, '盆數',      sub_hdr)
            r += 1

            # ── 盆餅 data rows (left & right sub-cols side by side) ───────
            section_start = r
            for idx, p in enumerate(left_ones):
                rr = section_start + idx
                ws.write(rr, base + 0, p['odoo_code'], cell_f)
                ws.write(rr, base + 1, p['name'],       name_f)
                pan = self._cell_value(p, p['grand_raw'])
                self._write_val(ws, rr, base + 2, pan, numf_int, numf_dec)
                # keep right side cells bordered even if no right item
                if idx >= len(right_ones):
                    ws.write_blank(rr, base + 3, None, cell_f)
                    ws.write_blank(rr, base + 4, None, cell_f)
                    ws.write_blank(rr, base + 5, None, cell_f)

            for idx, p in enumerate(right_ones):
                rr = section_start + idx
                ws.write(rr, base + 3, p['odoo_code'], cell_f)
                ws.write(rr, base + 4, p['name'],       name_f)
                pan = self._cell_value(p, p['grand_raw'])
                self._write_val(ws, rr, base + 5, pan, numf_int, numf_dec)
                # keep left side cells bordered if no left item at this row
                if idx >= len(left_ones):
                    ws.write_blank(rr, base + 0, None, cell_f)
                    ws.write_blank(rr, base + 1, None, cell_f)
                    ws.write_blank(rr, base + 2, None, cell_f)

        render(0)               # left mirror
        render(HALF + GAP)      # right mirror

        wb.close()
        type_label = '需求' if self.report_type == 'demand' else '送貨'
        filename = '燒爐紙_%s_%s.xlsx' % (type_label, self.start_date.strftime('%Y%m%d'))
        return self._download(output, filename)

    # ------------------------------------------------------------------
    def _download(self, output, filename):
        output.seek(0)
        xlsx_data = output.read()
        output.close()
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(xlsx_data),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % attachment.id,
            'target': 'self',
        }
