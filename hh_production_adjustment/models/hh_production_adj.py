from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare


class HhProductionAdj(models.Model):
    _name = 'hh.production.adj'
    _description = 'Production Adjustment'
    _order = 'name desc'

    name = fields.Char(string='Reference', readonly=True, default='New', copy=False)
    date = fields.Datetime(string='Date', required=True, default=fields.Datetime.now)
    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Warehouse', required=True,
        default=lambda self: self.env.user.property_warehouse_id
            or self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1),
    )
    note = fields.Text(string='Notes')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
    ], default='draft', string='Status', readonly=True)

    line_ids = fields.One2many('hh.production.adj.line', 'adj_id', string='Adjustment Lines')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('hh.production.adj') or 'New'
        return super().create(vals_list)

    def action_validate(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Only draft adjustments can be validated.'))
        if not self.line_ids:
            raise UserError(_('Please add at least one line before validating.'))

        location = self.warehouse_id.lot_stock_id
        inv_loss = self.env.ref('stock.location_inventory', raise_if_not_found=False)
        if not inv_loss:
            inv_loss = self.env['stock.location'].search([
                ('usage', '=', 'inventory'),
                ('company_id', 'in', [self.env.company.id, False]),
            ], limit=1)
        if not inv_loss:
            raise UserError(_('Inventory loss/adjustment location not found.'))

        # Check sufficient stock for deductions
        insufficient = []
        for line in self.line_ids:
            if line.qty < 0:
                available = sum(self.env['stock.quant'].search([
                    ('product_id', '=', line.product_id.id),
                    ('location_id', 'child_of', location.id),
                ]).mapped('quantity'))
                if available + line.qty < 0:
                    insufficient.append(_(
                        '• %s: required %.2f %s, available %.2f %s',
                        line.product_id.display_name,
                        abs(line.qty), line.product_uom_id.name,
                        available, line.product_uom_id.name,
                    ))
        if insufficient:
            raise UserError(_(
                'Insufficient stock in "%s":\n\n%s',
                location.complete_name,
                '\n'.join(insufficient),
            ))

        # Apply adjustments via stock.quant
        for line in self.line_ids:
            quant = self.env['stock.quant'].search([
                ('product_id', '=', line.product_id.id),
                ('location_id', '=', location.id),
                ('lot_id', '=', False),
                ('package_id', '=', False),
                ('owner_id', '=', False),
            ], limit=1)
            if quant:
                new_qty = quant.quantity + line.qty
            else:
                new_qty = line.qty
                quant = self.env['stock.quant'].create({
                    'product_id': line.product_id.id,
                    'location_id': location.id,
                    'quantity': 0,
                })
            quant.with_context(
                inventory_mode=True,
                inventory_name=self.name,
            ).write({'inventory_quantity': new_qty})
            quant._apply_inventory()

        self.state = 'done'

    def action_cancel(self):
        self.ensure_one()
        if self.state == 'done':
            raise UserError(_('Done adjustments cannot be cancelled. Please create a reverse adjustment.'))
        self.state = 'cancelled'

    def action_reset_draft(self):
        self.ensure_one()
        if self.state == 'cancelled':
            self.state = 'draft'

    def action_print(self):
        return self.env.ref('hh_production_adjustment.action_report_production_adj').report_action(self)


class HhProductionAdjLine(models.Model):
    _name = 'hh.production.adj.line'
    _description = 'Production Adjustment Line'

    adj_id = fields.Many2one('hh.production.adj', ondelete='cascade', required=True)
    product_id = fields.Many2one(
        'product.product', string='Product', required=True,
        domain="[('type', '!=', 'service')]",
    )
    product_uom_id = fields.Many2one(
        'uom.uom', string='Unit',
        compute='_compute_uom', store=True, readonly=False,
    )
    qty = fields.Float(
        string='Quantity (+/-)', required=True,
        digits='Product Unit of Measure',
        help="Positive to add stock, negative to deduct stock.",
    )

    @api.constrains('qty')
    def _check_qty(self):
        for line in self:
            if float_compare(line.qty, 0, precision_rounding=line.product_uom_id.rounding or 0.01) == 0:
                raise ValidationError(_(
                    'Quantity cannot be zero (product: %s). '
                    'Use a positive number to add stock or a negative number to deduct.',
                    line.product_id.display_name,
                ))

    @api.depends('product_id')
    def _compute_uom(self):
        for line in self:
            line.product_uom_id = line.product_id.uom_id
