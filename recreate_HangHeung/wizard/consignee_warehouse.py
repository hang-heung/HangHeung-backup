from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ConsigneeWarehouseWizard(models.TransientModel):
    _name = 'consignee.warehouse.wizard'
    _description = 'Onboard Consignee Warehouse'

    partner_id = fields.Many2one(
        'res.partner',
        string='Consignee Contact',
        required=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.ref('base.main_company', raise_if_not_found=False),
    )
    warehouse_code = fields.Char(
        string='Short Code',
        required=True,
        size=5,
        help="Up to 5 characters. Drives the picking-type name prefixes. Must be unique.",
    )
    warehouse_name = fields.Char(
        string='Warehouse Name',
        compute='_compute_warehouse_name',
        readonly=True,
    )

    @api.depends('partner_id')
    def _compute_warehouse_name(self):
        for wiz in self:
            name = wiz.partner_id.name or ''
            wiz.warehouse_name = ('Consignee - %s' % name) if name else ''

    def action_create_warehouse(self):
        self.ensure_one()
        code = (self.warehouse_code or '').strip().upper()
        if not code:
            raise UserError(_("Please enter a short code."))

        Warehouse = self.env['stock.warehouse'].sudo()
        if Warehouse.search_count([('code', '=', code)]):
            raise UserError(_("Warehouse short code '%s' is already in use.") % code)
        if Warehouse.search_count([
            ('partner_id', '=', self.partner_id.id),
            ('company_id', '=', self.company_id.id),
        ]):
            raise UserError(_(
                "A warehouse already exists for consignee '%s' in this company."
            ) % self.partner_id.name)

        warehouse = Warehouse.with_company(self.company_id.id).create({
            'name': self.warehouse_name,
            'code': code,
            'company_id': self.company_id.id,
            'partner_id': self.partner_id.id,
        })

        return {
            'type': 'ir.actions.act_window',
            'name': _('Consignee Warehouse'),
            'res_model': 'stock.warehouse',
            'res_id': warehouse.id,
            'view_mode': 'form',
            'target': 'current',
        }
