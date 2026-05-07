from collections import defaultdict
from dateutil.relativedelta import relativedelta
from odoo.exceptions import UserError, ValidationError
from odoo import models, fields, api, _, SUPERUSER_ID
from odoo.tools import float_compare, groupby
import logging

_logger = logging.getLogger(__name__)

# Internal shop partner IDs that may NOT be used as Dropship Address on a PO.
# Names: AB1, AIR2, AIR3, AIR4, CB1, DP1, KF1, MK1, MS1, NP1, SS1, ST1,
#        TP1, TLP, TST, WK1, YLF, YMS
FORBIDDEN_DROPSHIP_PARTNER_IDS = [
    8885, 8886, 8887, 8888, 8889, 8890, 8891, 8892, 8893,
    8896, 8897, 8898, 8899, 8901, 8904, 8905, 8919, 8940,
]


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    remark = fields.Text(
        string='備註',
        copy=True,
        help="Carried from the upstream SO/PO of the intercompany chain.",
    )
    is_wedding_order = fields.Boolean(
        string='嫁囍單',
        default=False,
        copy=False,
        help="Isolation flag carried from the originating SO; this PO will not merge with non-flagged orders.",
    )
    is_b2b_order = fields.Boolean(
        string='B2B單',
        default=False,
        copy=False,
        help="Isolation flag carried from the originating SO; this PO will not merge with non-flagged orders.",
    )

    def inter_company_create_sale_order(self, company):
        """Skip when target company == source PO company. Mirror of the
        same-company guard on sale_order.inter_company_create_purchase_order:
        prevents a self-SO when a vendor's commercial_partner_id resolves to
        the source company's own partner."""
        same_co = self.filtered(lambda r: r.company_id and r.company_id.id == company.id)
        cross_co = self - same_co
        if cross_co:
            return super(PurchaseOrder, cross_co).inter_company_create_sale_order(company)
        return False

    @api.constrains('dest_address_id')
    def _check_dest_address_not_internal_shop(self):
        for po in self:
            if po.dest_address_id and po.dest_address_id.id in FORBIDDEN_DROPSHIP_PARTNER_IDS:
                raise ValidationError(_(
                    "'%(name)s' cannot be selected as the Dropship Address. "
                    "Internal shop contacts are not valid dropship destinations."
                ) % {'name': po.dest_address_id.name})


    @api.model
    def _default_picking_type(self):
        curr_company = self.env.context.get('allowed_company_ids')[0]
        if curr_company == 2:
            return self.env['stock.picking.type'].search([('code', '=', 'dropship'), ('company_id', '=', 2)], limit=1).id
        elif curr_company == 1:
            return self.env['res.users'].search([('id', '=', self.env.user.id)]).default_receipt_type
    

    @api.model
    def _default_dest_address(self):
        return self.env['res.users'].search([('id', '=', self.env.user.id)]).default_dest_address


    partner_id = fields.Many2one(
        'res.partner',
        string='Vendor',
        required=True,
        change_default=True,
        tracking=True,
        check_company=True,
        default=lambda self: self.get_default_vendor(),
        help="You can find a vendor by its Name, TIN, Email or Internal Reference."
    )

    picking_type_id = fields.Many2one(
        'stock.picking.type', 
        'Deliver To', 
        required=False, 
        default=_default_picking_type,
        domain="['|', ('warehouse_id', '=', False), ('warehouse_id.company_id', '=', company_id)]",
        help="This will determine operation type of incoming shipment"
    )

    dest_address_id = fields.Many2one('res.partner', store=True, readonly=False, default=_default_dest_address)


    @api.onchange('picking_type_id')
    def onchange_dest_address_id(self):
        for purchase_order in self:
            purchase_order.dest_address_id = purchase_order.picking_type_id.warehouse_id.partner_id.id


    def copy(self, default=None):
        res = super(PurchaseOrder,self).copy(default=default)
        if self.partner_id.purchase_auto_confirm:
            self.button_confirm()
        return res


    @api.model
    def get_default_vendor(self):
        partner = False
        curr_company = self.env.context.get("allowed_company_ids")[0]
        if curr_company == 1:
            partner = self.env['res.partner'].search([('id', '=', 8883)], limit=1)
        elif curr_company == 2:
            partner = self.env['res.partner'].search([('name', '=', 'Hang Heung Cake Shop Company Limited')], limit=1)
        return partner.id if partner else False
    

    @api.onchange('company_id')
    def _onchange_company_id(self):
        pass

    def _prepare_sale_order_data(self, name, partner, company, direct_delivery_address):
        result = super()._prepare_sale_order_data(name, partner, company, direct_delivery_address)
        if self.origin:
            result['client_order_ref'] = f"{self.origin}-{self.name}"
        result['intercompany_source_po_name'] = self.name
        # Carry remark + isolation flags downstream onto the created SO.
        result['remark'] = self.remark or False
        result['is_wedding_order'] = self.is_wedding_order
        result['is_b2b_order'] = self.is_b2b_order
        # When the downstream SO is being created in HangHeung (company 3) and
        # carries a remark, also stamp the picking-note vals so the eventual
        # delivery picking inherits 備註 (used by the DN List Report's Remark
        # column, which reads stock.picking.note). The actual write happens in
        # sale.order._action_confirm() once pickings exist.
        return result

    def button_cancel(self):
        result = super().button_cancel()
        for po in self:
            downstream_sos = self.env['sale.order'].sudo().search([
                ('auto_purchase_order_id', '=', po.id),
                ('state', '!=', 'cancel'),
            ])
            if downstream_sos:
                downstream_sos.with_user(SUPERUSER_ID)._action_cancel()
                for so in downstream_sos:
                    so.message_post(body=_(
                        "Cancelled via chain cascade from %(po_name)s (company %(company)s).",
                        po_name=po.name, company=po.company_id.name,
                    ))
        return result


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    @api.model
    def _prepare_purchase_order_line_from_procurement(
        self, product_id, product_qty, product_uom, location_dest_id, name, origin, company_id, values, po
    ):
        """Back-fill sale_line_id when core didn't set it.

        Core sets res['sale_line_id'] = values.get('sale_line_id', False).
        In HoyMay's Pop+MTO chain that key is dropped before _run_buy is
        called, so the standard sale_purchase smart button on the SO
        (counts via purchase.order.line.sale_line_id) shows 0 even though
        a PO clearly exists for the SO. Resolve the source SO via the
        existing multi-fallback (sale_line_id -> group_id -> origins),
        match its line to the procured product, and set sale_line_id.
        """
        res = super()._prepare_purchase_order_line_from_procurement(
            product_id, product_qty, product_uom, location_dest_id,
            name, origin, company_id, values, po,
        )
        if res.get('sale_line_id'):
            return res
        StockRule = self.env['stock.rule'].sudo()
        source_so = StockRule._hh_find_source_sale_order(
            [values], origins={origin} if origin else None,
        )
        if not source_so:
            return res
        so_line = source_so.order_line.filtered(
            lambda l: l.product_id.id == product_id.id and not l.display_type
        )
        if so_line:
            res['sale_line_id'] = so_line[0].id
        return res


class StockRule(models.Model):
    _inherit = 'stock.rule'

    def _hh_find_source_sale_order(self, values_list, origins=None):
        """Resolve the source sale.order from procurement values + origins.

        Multi-fallback because sale_line_id may not survive the procurement
        chain reliably (HoyMay's Pop+MTO chain in particular drops it before
        _prepare_purchase_order is called).

        Tries, in order:
          1. values[i]['sale_line_id'] -> sale.order.line.order_id
          2. values[i]['group_id'].name -> sale.order matching that name
          3. any string in origins that looks like an SO name
        """
        SO = self.env['sale.order'].sudo()
        SOL = self.env['sale.order.line'].sudo()
        for values in values_list or []:
            sale_line_id = values.get('sale_line_id') if values else None
            if sale_line_id:
                line = SOL.browse(sale_line_id).exists()
                if line and line.order_id:
                    return line.order_id
            group = values.get('group_id') if values else None
            grp_name = None
            if group is not None:
                grp_name = group.name if hasattr(group, 'name') else None
                if grp_name is None and isinstance(group, int):
                    grp_rec = self.env['procurement.group'].sudo().browse(group)
                    grp_name = grp_rec.name if grp_rec.exists() else None
            if grp_name:
                so = SO.search([('name', '=', grp_name)], limit=1)
                if so:
                    return so
        for origin in (origins or []):
            for part in (origin or '').split(', '):
                candidate = part.split('-')[-1].strip()
                if candidate:
                    so = SO.search([('name', '=', candidate)], limit=1)
                    if so:
                        return so
        return SO

    @api.model
    def _make_po_get_domain(self, company_id, values, partner):
        """Per-SO isolation: every SO-driven procurement gets its own PO.

        When a procurement traces back to a sale.order line, restrict the
        merge-domain to require an existing PO whose `origin` matches THIS
        SO's name exactly. Uses multi-fallback resolution so we don't miss
        SO origin when sale_line_id is dropped from values mid-chain.
        """
        domain = super()._make_po_get_domain(company_id, values, partner)
        order = self._hh_find_source_sale_order([values])
        if order:
            domain += (('origin', '=', order.name),)
        return domain

    @api.model
    def _prepare_purchase_order(self, company_id, origins, values):
        """Carry remark + isolation flags + dest_address onto procurement POs.

        dest_address_id is set to the source SO's partner_shipping_id so the
        PO's dropship/destination address always mirrors the customer's
        delivery address. Multi-fallback resolution (sale_line_id, group_id,
        origins) so the propagation lands even when sale_line_id is dropped
        from values further up the chain.
        """
        res = super()._prepare_purchase_order(company_id, origins, values)
        order = self._hh_find_source_sale_order(values, origins)
        if order:
            res['remark'] = order.remark or False
            res['is_wedding_order'] = order.is_wedding_order
            res['is_b2b_order'] = order.is_b2b_order
            if order.partner_shipping_id:
                res['dest_address_id'] = order.partner_shipping_id.id
        return res

    @api.model
    def _run_buy(self, procurements):
        procurements_by_po_domain = defaultdict(list)
        errors = []
        for procurement, rule in procurements:

            # Get the schedule date in order to find a valid seller
            procurement_date_planned = fields.Datetime.from_string(procurement.values['date_planned'])

            supplier = False
            company_id = rule.company_id or procurement.company_id
            if procurement.values.get('supplierinfo_id'):
                supplier = procurement.values['supplierinfo_id']
            elif procurement.values.get('orderpoint_id') and procurement.values['orderpoint_id'].supplier_id:
                supplier = procurement.values['orderpoint_id'].supplier_id
            else:
                supplier = procurement.product_id.with_company(company_id.id)._select_seller(
                    partner_id=self._get_partner_id(procurement.values, rule),
                    quantity=procurement.product_qty,
                    date=max(procurement_date_planned.date(), fields.Date.today()),
                    uom_id=procurement.product_uom)

            # Fall back on a supplier for which no price may be defined. Not ideal, but better than
            # blocking the user.
            supplier = supplier or procurement.product_id._prepare_sellers(False).filtered(
                lambda s: not s.company_id or s.company_id == company_id
            )[:1]

            if not supplier:
                msg = _('There is no matching vendor price to generate the purchase order for product %s (no vendor defined, minimum quantity not reached, dates not valid, ...). Go on the product form and complete the list of vendors.', procurement.product_id.display_name)
                errors.append((procurement, msg))

            partner = supplier.partner_id
            # we put `supplier_info` in values for extensibility purposes
            procurement.values['supplier'] = supplier
            procurement.values['propagate_cancel'] = rule.propagate_cancel

            domain = rule._make_po_get_domain(company_id, procurement.values, partner)
            procurements_by_po_domain[domain].append((procurement, rule))

        if errors:
            raise UserError('\n'.join(msg for _, msg in errors))
        

        for domain, procurements_rules in procurements_by_po_domain.items():
            # Get the procurements for the current domain.
            # Get the rules for the current domain. Their only use is to create
            # the PO if it does not exist.
            procurements, rules = zip(*procurements_rules)

            # Get the set of procurement origin for the current domain.
            origins = set([p.origin for p in procurements if p.origin])
            # Force per-SO isolation: when ANY procurement in this group
            # traces back to a sale.order, skip the merge-search entirely so
            # a brand-new PO is always created. Use multi-fallback resolution
            # (sale_line_id, group_id, origin string) because the simple
            # sale_line_id check above isn't always populated for the BUY
            # rule's procurement values in the HoyMay Pop+MTO chain.
            source_so = self._hh_find_source_sale_order(
                [p.values for p in procurements],
                origins,
            )
            if source_so:
                po = self.env['purchase.order']
            else:
                po = self.env['purchase.order'].sudo().search([dom for dom in domain], limit=1)
            company_id = rules[0].company_id or procurements[0].company_id
            if not po:
                positive_values = [p.values for p in procurements if float_compare(p.product_qty, 0.0, precision_rounding=p.product_uom.rounding) >= 0]
                if positive_values:
                    # We need a rule to generate the PO. However the rule generated
                    # the same domain for PO and the _prepare_purchase_order method
                    # should only uses the common rules's fields.
                    vals = rules[0]._prepare_purchase_order(company_id, origins, positive_values)
                    po_origin = self.env['purchase.order'].search([('company_id', '=', 1), ('partner_ref', '=', vals['origin'])])
                    # The company_id is the same for all procurements since
                    # _make_po_get_domain add the company in the domain.
                    # We use SUPERUSER_ID since we don't want the current user to be follower of the PO.
                    # Indeed, the current user may be a user without access to Purchase, or even be a portal user.
                    if vals['company_id'] == 2:
                        picking_type_id = self.env['stock.picking.type'].search([('code', '=', 'dropship'), ('company_id', '=', 2)], limit=1).id
                        if po_origin:
                            dest_address = po_origin.dest_address_id.id
                        else:
                            sale_order = self.env['sale.order'].search([('name', '=', procurement.origin)], limit=1)
                            if sale_order and sale_order.partner_shipping_id:
                                dest_address = sale_order.partner_shipping_id.id
                            else:
                                dest_address = self.env['res.users'].search([('id', '=', self.env.context['uid'])]).default_dest_address.id
                        if picking_type_id:
                            vals['picking_type_id'] = picking_type_id
                        if dest_address:
                            vals['dest_address_id'] = dest_address
                    po = self.env['purchase.order'].with_company(company_id).with_user(SUPERUSER_ID).create(vals)
            else:
                # If a purchase order is found, adapt its `origin` field.
                if po.origin:
                    missing_origins = origins - set(po.origin.split(', '))
                    if missing_origins:
                        po.write({'origin': po.origin + ', ' + ', '.join(missing_origins)})
                else:
                    po.write({'origin': ', '.join(origins)})
                if po.company_id.id == 2:
                    picking_type_id = self.env['stock.picking.type'].search([('code', '=', 'dropship'), ('company_id', '=', 2)], limit=1).id
                    dest_address = self.env['res.users'].search([('id', '=', self.env.context['uid'])]).default_dest_address.id
                    po.write({'picking_type_id': picking_type_id, 'dest_address_id': dest_address})

            procurements_to_merge = self._get_procurements_to_merge(procurements)
            procurements = self._merge_procurements(procurements_to_merge)

            po_lines_by_product = {}
            grouped_po_lines = groupby(po.order_line.filtered(lambda l: not l.display_type and l.product_uom == l.product_id.uom_po_id), key=lambda l: l.product_id.id)
            for product, po_lines in grouped_po_lines:
                po_lines_by_product[product] = self.env['purchase.order.line'].concat(*po_lines)
            po_line_values = []
            for procurement in procurements:
                po_lines = po_lines_by_product.get(procurement.product_id.id, self.env['purchase.order.line'])
                po_line = po_lines._find_candidate(*procurement)

                if po_line:
                    # If the procurement can be merge in an existing line. Directly
                    # write the new values on it.
                    vals = self._update_purchase_order_line(procurement.product_id,
                        procurement.product_qty, procurement.product_uom, company_id,
                        procurement.values, po_line)
                    po_line.sudo().write(vals)
                else:
                    if float_compare(procurement.product_qty, 0, precision_rounding=procurement.product_uom.rounding) <= 0:
                        # If procurement contains negative quantity, don't create a new line that would contain negative qty
                        continue
                    # If it does not exist a PO line for current procurement.
                    # Generate the create values for it and add it to a list in
                    # order to create it in batch.
                    partner = procurement.values['supplier'].partner_id
                    po_line_values.append(self.env['purchase.order.line']._prepare_purchase_order_line_from_procurement(
                        *procurement, po))
                    # Check if we need to advance the order date for the new line
                    order_date_planned = procurement.values['date_planned'] - relativedelta(
                        days=procurement.values['supplier'].delay)
                    if fields.Date.to_date(order_date_planned) < fields.Date.to_date(po.date_order):
                        po.date_order = order_date_planned
            self.env['purchase.order.line'].sudo().create(po_line_values)

            if po.origin:
                origin_parts = po.origin.split(', ')
                new_parts = []
                for part in origin_parts:
                    if '-' in part:
                        new_parts.append(part)
                        continue
                    so = self.env['sale.order'].sudo().search([('name', '=', part)], limit=1)
                    if so and so.client_order_ref:
                        new_parts.append(f"{so.client_order_ref}-{part}")
                    else:
                        new_parts.append(part)
                chained_origin = ', '.join(new_parts)
                if chained_origin != po.origin:
                    po.write({'origin': chained_origin})

            # Auto-confirm immediately whenever the partner has the flag.
            # The earlier "defer until POS payment" gate has been dropped at
            # user request; SO confirm now drives the full intercompany
            # cascade (Hoymay PO -> That's SO/PO -> HangHeung SO/PO) without
            # waiting for the customer to settle in POS. The pos_payment
            # hook (_maybe_confirm_linked_pos) becomes a no-op when POs are
            # already confirmed and is kept only as a defensive backstop.
            if po.partner_id.purchase_auto_confirm:
                po.button_confirm()
        