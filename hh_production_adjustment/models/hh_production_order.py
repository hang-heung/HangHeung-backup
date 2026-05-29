from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class HhProductionOrder(models.Model):
    _name = 'hh.production.order'
    _description = 'Production Order'
    _order = 'name desc'

    name = fields.Char(string='Reference', readonly=True, default='New', copy=False)
    date = fields.Datetime(string='Date', required=True, default=fields.Datetime.now)
    note = fields.Text(string='Notes')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
    ], default='draft', string='Status', readonly=True)

    consume_warehouse_id = fields.Many2one(
        'stock.warehouse', string='Consume From',
        required=True,
        default=lambda self: self.env.user.property_warehouse_id
            or self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1),
        help="Raw materials will be consumed from this warehouse's stock location.",
    )
    produce_warehouse_id = fields.Many2one(
        'stock.warehouse', string='Produce To',
        required=True,
        default=lambda self: self.env.user.property_warehouse_id
            or self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1),
        help="Produced goods will be added to this warehouse's stock location.",
    )


    reason_code_id = fields.Many2one(
        'reason.code', string='Reason Code',
        help="Reason for this production order.",
    )

    consume_line_ids = fields.One2many(
        'hh.production.order.line', 'order_id',
        domain=[('line_type', '=', 'consume')],
        string='Raw Materials (Consume)',
    )
    produce_line_ids = fields.One2many(
        'hh.production.order.line', 'order_id',
        domain=[('line_type', '=', 'produce')],
        string='Produced Goods',
    )

    consumption_picking_id = fields.Many2one('stock.picking', string='Consumption Transfer', readonly=True)
    output_picking_id = fields.Many2one('stock.picking', string='Output Transfer', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('hh.production.order') or 'New'
        return super().create(vals_list)

    def action_validate(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Only draft orders can be validated.'))
        if not self.consume_line_ids and not self.produce_line_ids:
            raise UserError(_('Please add at least one line before validating.'))

        # Look up op types from company config
        config = self.env['hh.production.config'].search([
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        if not config:
            raise UserError(_(
                'No Production Order configuration found for company "%s". '
                'Please ask your administrator to configure it under '
                'Inventory → Configuration → Production Order Config.',
                self.env.company.name,
            ))
        consume_type = config.consume_type_id
        output_type = config.output_type_id

        # Locations come from the selected warehouses on this order
        consume_company_virtual = self.env['stock.location'].search([
            ('usage', '=', 'production'),
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        if not consume_company_virtual:
            raise UserError(_('No virtual Production location found for company "%s".', self.env.company.name))

        src_location = self.consume_warehouse_id.lot_stock_id
        dst_location = self.produce_warehouse_id.lot_stock_id

        # Stock sufficiency check
        insufficient = []
        for line in self.consume_line_ids:
            available = sum(self.env['stock.quant'].search([
                ('product_id', '=', line.product_id.id),
                ('location_id', 'child_of', src_location.id),
            ]).mapped('quantity'))
            if available < line.qty:
                insufficient.append(_(
                    '• %s: required %.2f %s, available %.2f %s',
                    line.product_id.display_name,
                    line.qty, line.product_uom_id.name,
                    available, line.product_uom_id.name,
                ))
        if insufficient:
            raise UserError(_(
                'Insufficient stock in "%s" for the following products:\n\n%s\n\n'
                'Please adjust quantities or replenish stock before validating.',
                src_location.complete_name,
                '\n'.join(insufficient),
            ))

        picking_obj = self.env['stock.picking']
        consume_pick = False
        output_pick = False

        if self.consume_line_ids:
            consume_pick = picking_obj.create({
                'picking_type_id': consume_type.id,
                'location_id': src_location.id,
                'location_dest_id': consume_company_virtual.id,
                'origin': self.name,
                'note': self.note or '',
                'move_ids': [(0, 0, {
                    'name': line.product_id.display_name,
                    'product_id': line.product_id.id,
                    'product_uom_qty': line.qty,
                    'product_uom': line.product_uom_id.id,
                    'location_id': src_location.id,
                    'location_dest_id': consume_company_virtual.id,
                }) for line in self.consume_line_ids],
            })
            consume_pick.action_confirm()
            for move in consume_pick.move_ids:
                move.quantity = move.product_uom_qty
            consume_pick.with_context(skip_backorder=True).button_validate()

        if self.produce_line_ids:
            output_pick = picking_obj.create({
                'picking_type_id': output_type.id,
                'location_id': consume_company_virtual.id,
                'location_dest_id': dst_location.id,
                'origin': self.name,
                'note': self.note or '',
                'move_ids': [(0, 0, {
                    'name': line.product_id.display_name,
                    'product_id': line.product_id.id,
                    'product_uom_qty': line.qty,
                    'product_uom': line.product_uom_id.id,
                    'location_id': consume_company_virtual.id,
                    'location_dest_id': dst_location.id,
                }) for line in self.produce_line_ids],
            })
            output_pick.action_confirm()
            for move in output_pick.move_ids:
                move.quantity = move.product_uom_qty
            output_pick.with_context(skip_backorder=True).button_validate()

        self.write({
            'state': 'done',
            'consumption_picking_id': consume_pick.id if consume_pick else False,
            'output_picking_id': output_pick.id if output_pick else False,
        })

    def action_cancel(self):
        self.ensure_one()
        if self.state == 'done':
            raise UserError(_('Done orders cannot be cancelled. Please do a reverse adjustment.'))
        self.state = 'cancelled'

    def action_reset_draft(self):
        self.ensure_one()
        if self.state == 'cancelled':
            self.state = 'draft'

    def action_view_pickings(self):
        picks = (self.consumption_picking_id | self.output_picking_id).filtered(bool)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Transfers'),
            'res_model': 'stock.picking',
            'view_mode': 'list,form',
            'domain': [('id', 'in', picks.ids)],
        }

    def action_print(self):
        return self.env.ref('hh_production_adjustment.action_report_production_order').report_action(self)


class HhProductionOrderLine(models.Model):
    _name = 'hh.production.order.line'
    _description = 'Production Order Line'

    order_id = fields.Many2one('hh.production.order', ondelete='cascade', required=True)
    line_type = fields.Selection([
        ('consume', 'Consume'),
        ('produce', 'Produce'),
    ], required=True)
    product_id = fields.Many2one(
        'product.product', string='Product', required=True,
        domain="[('type', '!=', 'service')]",
    )
    product_uom_id = fields.Many2one(
        'uom.uom', string='Unit',
        compute='_compute_uom', store=True, readonly=False,
    )
    qty = fields.Float(string='Quantity', required=True, digits='Product Unit of Measure')

    @api.constrains('qty', 'line_type')
    def _check_qty(self):
        for line in self:
            if line.qty <= 0:
                label = 'Raw Materials (Consume)' if line.line_type == 'consume' else 'Produced Goods'
                raise ValidationError(_(
                    'Quantity must be greater than zero on "%s" tab (product: %s). '
                    'Enter a positive number — the tab determines whether stock is added or deducted.',
                    label, line.product_id.display_name,
                ))

    @api.depends('product_id')
    def _compute_uom(self):
        for line in self:
            line.product_uom_id = line.product_id.uom_id
