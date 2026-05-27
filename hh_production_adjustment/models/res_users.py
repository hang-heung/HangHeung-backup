from odoo import fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    production_order_user = fields.Boolean(
        string='Production Order User',
        compute='_compute_production_order_user',
        inverse='_inverse_production_order_user',
        store=False,
        help="If enabled, this user can create and validate Production Orders.",
    )
    production_adj_user = fields.Boolean(
        string='Production Adjustment User',
        compute='_compute_production_adj_user',
        inverse='_inverse_production_adj_user',
        store=False,
        help="If enabled, this user can create and validate Production Adjustments.",
    )

    def _compute_production_order_user(self):
        group = self.env.ref('hh_production_adjustment.group_hh_production_user')
        for user in self:
            user.production_order_user = group in user.groups_id

    def _inverse_production_order_user(self):
        group = self.env.ref('hh_production_adjustment.group_hh_production_user')
        for user in self:
            if user.production_order_user:
                user.sudo().groups_id = [(4, group.id)]
            else:
                user.sudo().groups_id = [(3, group.id)]

    def _compute_production_adj_user(self):
        group = self.env.ref('hh_production_adjustment.group_hh_production_adj_user')
        for user in self:
            user.production_adj_user = group in user.groups_id

    def _inverse_production_adj_user(self):
        group = self.env.ref('hh_production_adjustment.group_hh_production_adj_user')
        for user in self:
            if user.production_adj_user:
                user.sudo().groups_id = [(4, group.id)]
            else:
                user.sudo().groups_id = [(3, group.id)]
