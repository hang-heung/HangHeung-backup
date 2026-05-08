import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _name = 'stock.picking'
    _inherit = ['stock.picking', 'product.catalog.mixin']

    has_dropship_origin = fields.Boolean(string='Has Dropship', default=False, compute="_compute_has_dropship")
    dropship_validated = fields.Boolean(string='Dropship Validated', default=False)

    reason_code = fields.Many2one(
        'reason.code',
        string='Reason Code',
        domain="[('odoo_function_ids', 'in', picking_type_id)]",
        store=True
    )

    @api.model_create_multi
    def create(self, vals_list):
        pickings = super().create(vals_list)
        if not self.env.context.get('skip_auto_confirm'):
            for picking in pickings:
                if picking.state == 'draft' and picking.move_ids:
                    try:
                        picking.action_confirm()
                    except Exception as e:
                        _logger.warning(
                            "Auto-confirm skipped for picking %s: %s",
                            picking.name or '?', e,
                        )
        return pickings

    @api.onchange('picking_type_id')
    def _onchange_picking_type_id(self):
        for record in self:
            record.reason_code = False

    def _compute_has_dropship(self):
        for record in self:
            if record.origin:
                origin_po = record.origin.split('-')[-1].strip()

                dropship = self.env['stock.picking'].sudo().with_company(2).search([
                    ('origin', '=', origin_po),
                    ('picking_type_id.code', '=', 'dropship')
                ], limit=1)

                record.has_dropship_origin = bool(dropship)
            else:
                record.has_dropship_origin = False

    def action_set_qty_to_demand(self):
        """One-click 'fill received qty = demand' on every move of an
        incoming receipt. Does NOT validate -- the user still needs to
        click Validate. Only operates on moves not yet done/cancelled.
        """
        for picking in self:
            self._hh_autofill_received_qty(picking)
        return True

    @staticmethod
    def _hh_autofill_received_qty(picking):
        """Set move.quantity = move.product_uom_qty + picked=True on every
        non-done/cancel move. Used by both the manual button and the
        action_confirm/_action_assign hooks below.

        Always overwrites quantity with demand (does NOT preserve any
        partial reservation done by action_assign) -- a partial reserve
        from a transit/stocked source location would otherwise leave the
        cashier silently shipping less than the PO demanded.
        """
        for move in picking.move_ids:
            if move.state in ('done', 'cancel'):
                continue
            move.quantity = move.product_uom_qty
            move.picked = True

    def _hh_should_autofill_on_ready(self):
        """True for Hoymay (company 1) incoming receipts. Used to gate
        the auto-fill that runs on action_confirm / _action_assign so
        the cashier never has to type qty = demand line by line.
        """
        self.ensure_one()
        return (
            self.company_id.id == 1
            and self.picking_type_id.code == 'incoming'
        )

    def action_confirm(self):
        res = super().action_confirm()
        for picking in self:
            if picking._hh_should_autofill_on_ready():
                self._hh_autofill_received_qty(picking)
        return res

    def _action_assign(self):
        res = super()._action_assign()
        for picking in self:
            if picking._hh_should_autofill_on_ready():
                self._hh_autofill_received_qty(picking)
        return res

    def action_cancel(self):
        # HH-CUSTOM: when POS sync_from_ui tries to cancel a Hoymay SO
        # picking after zeroing its demand, refuse. POS settlement is
        # payment-only in our pre-order workflow; the goods still need
        # to flow through the warehouse picking chain.
        if self.env.context.get('hh_pos_protect_hoymay_pickings'):
            keep = self.filtered(
                lambda p: p.company_id.id == 1 and (p.origin or '').startswith('HM/')
            )
            return (self - keep).action_cancel()
        return super().action_cancel()

    def _find_related_hh_outgoing(self):
        """Locate the HangHeung outgoing delivery in the same chain.

        Used to gate validation of a Hoymay incoming receipt: the goods
        physically leave HangHeung's warehouse first; only after that
        delivery is `done` may Hoymay claim receipt.

        Match strategy: any outgoing picking in HangHeung (company 3)
        whose `origin` string contains this picking's source token (the
        last '-' segment of `self.origin`, typically the Hoymay PO name).
        Returns an empty recordset if no chain is found (e.g. orders that
        don't fan out to HangHeung).
        """
        self.ensure_one()
        if not self.origin:
            return self.env['stock.picking']
        token = self.origin.split('-')[-1].strip()
        if not token:
            return self.env['stock.picking']
        return self.env['stock.picking'].sudo().with_company(False).search([
            ('company_id', '=', 3),
            ('picking_type_id.code', '=', 'outgoing'),
            ('origin', 'like', '%' + token + '%'),
            ('state', '!=', 'cancel'),
        ], limit=1)

    def button_validate(self):
        # HH-CUSTOM: a Hoymay incoming receipt cannot be validated until
        # the HangHeung outgoing delivery in the same intercompany chain
        # has been validated -- the goods must have left HangHeung's
        # warehouse before Hoymay can claim receipt.
        for picking in self:
            if (
                picking.company_id.id == 1
                and picking.picking_type_id.code == 'incoming'
            ):
                hh = picking._find_related_hh_outgoing()
                if hh and hh.state != 'done':
                    raise UserError(_(
                        "Cannot validate %(name)s yet — the upstream "
                        "HangHeung delivery %(hh)s is in '%(state)s' state. "
                        "Validate the HangHeung delivery first.",
                        name=picking.name,
                        hh=hh.name,
                        state=dict(hh._fields['state'].selection).get(hh.state, hh.state),
                    ))
        return super().button_validate()

    def button_dropship_validate(self):
        if self.origin:
            origin_po = self.origin.split('-')[-1].strip()

            dropship = self.env['stock.picking'].sudo().with_company(2).search([
                ('origin', '=', origin_po),
                ('picking_type_id.code', '=', 'dropship')
            ], limit=1)

            if dropship:
                # HH-CUSTOM: dropship moves go between virtual partner
                # locations (no real reservation), so they sit at
                # state='confirmed' with quantity=0 -- which makes the
                # standard button_validate refuse with "no reserved qty".
                # Pre-populate move.quantity = product_uom_qty so the
                # validation passes.
                for move in dropship.move_ids:
                    if move.state not in ('done', 'cancel') and not move.quantity:
                        move.quantity = move.product_uom_qty
                        move.picked = True
                dropship.button_validate()
                dropship.message_post(
                    body=_("The dropship order %s has been successfully validated by %s.") % (dropship.name, self.company_id.name)
                )
                self.message_post(body=_("Dropship order %s has been successfully validated") % (dropship.name))
                self.dropship_validated = True
                dropship.dropship_validated = True

    def _pre_action_done_hook(self):
        res = super(StockPicking, self)._pre_action_done_hook()
        for picking in self:
            for move in picking.move_ids:
                if move.scrapped:
                    continue
                if move.product_uom_qty > move.quantity and not picking.reason_code:
                    move.picked = True
                    return {
                        'name': 'Provide Reason Code',
                        'type': 'ir.actions.act_window',
                        'res_model': 'wizard.code',
                        'view_mode': 'form',
                        'view_id': self.env.ref('recreate_HangHeung.view_reason_wizard_form1').id,
                        'target': 'new',
                        'context': {
                            'picking_type_id': picking.picking_type_id.id,
                            'active_id': picking.id,
                            'active_model': 'stock.picking',
                        }
                    }
        return res

    full_origin_chain = fields.Char(
        string="Origin Chain",
        compute="_compute_full_origin_chain",
        store=True
    )

    @api.depends('origin')
    def _compute_full_origin_chain(self):
        for picking in self:
            chain = []
            visited = set()

            search_key = False

            if picking.origin:
                parts = [p.strip() for p in picking.origin.split('-') if p.strip()]

                if parts:
                    if len(parts) > 1:
                        chain.append(parts[0])
                    search_key = parts[-1]

            depth = 0
            max_depth = 10

            while search_key and search_key not in visited and depth < max_depth:
                visited.add(search_key)
                depth += 1

                chain.append(search_key)
                next_key = False

                # Search SO
                so = self.env['sale.order'].sudo().with_company(False).search([('name', '=', search_key)], limit=1)

                if so:
                    source = so.origin or so.client_order_ref
                    if source:
                        next_key = source.split('-')[-1].strip()

                    search_key = next_key
                    continue

                # Search PO
                po = self.env['purchase.order'].sudo().with_company(False).search([('name', '=', search_key)], limit=1)

                if po and po.origin:
                    next_key = po.origin.split('-')[-1].strip()

                search_key = next_key

            picking.full_origin_chain = " - ".join(chain)

    def _is_readonly(self):
        self.ensure_one()
        return self.state in ('done', 'cancel')

    def _get_product_catalog_domain(self):
        domain = super()._get_product_catalog_domain()
        return domain + [('is_storable', '=', True)]

    def _get_product_catalog_record_lines(self, product_ids, child_field=False, **kwargs):
        grouped = {}
        for move in self.move_ids_without_package:
            if move.product_id.id in product_ids:
                grouped.setdefault(move.product_id, self.env['stock.move'])
                grouped[move.product_id] |= move
        return grouped

    def _get_product_catalog_order_data(self, products, **kwargs):
        result = super()._get_product_catalog_order_data(products, **kwargs)
        for product in products:
            entry = result.setdefault(product.id, {'productType': product.type})
            entry['price'] = 0.0
        return result

    def _update_order_line_info(self, product_id, quantity, **kwargs):
        self.ensure_one()
        if self._is_readonly():
            raise UserError(_(
                "You can't modify lines of a picking in state '%s'."
            ) % dict(self._fields['state'].selection).get(self.state, self.state))

        product = self.env['product.product'].browse(product_id)
        existing = self.move_ids_without_package.filtered(lambda m: m.product_id == product)

        if existing:
            if quantity <= 0:
                existing.unlink()
            else:
                existing[0].product_uom_qty = quantity
                if len(existing) > 1:
                    (existing - existing[0]).unlink()
        elif quantity > 0:
            self.env['stock.move'].create({
                'picking_id': self.id,
                'product_id': product.id,
                'product_uom_qty': quantity,
                'product_uom': product.uom_id.id,
                'name': product.display_name,
                'location_id': self.location_id.id,
                'location_dest_id': self.location_dest_id.id,
                'company_id': self.company_id.id,
                'picking_type_id': self.picking_type_id.id,
            })
        return 0.0