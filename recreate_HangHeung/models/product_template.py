from odoo import models, fields, api, _
from datetime import datetime
import logging
from odoo.exceptions import ValidationError, UserError
import re

_logger = logging.getLogger(__name__)


# HH-CUSTOM: users in this group are forbidden from creating new products.
# All their other access rights stay intact -- the check fires only at
# product.template / product.product create() time. Used for the 18 POS
# shop logins (YLF, MK1, CB1, ... AIR4) so cashiers can't accidentally
# add SKUs while still keeping Inventory/Sales/Purchase Administrator
# powers for their store operations.
_NO_PRODUCT_CREATE_GROUP_XID = 'recreate_HangHeung.group_pos_shop_no_product_create'


def _hh_block_product_create_for_shop_user(env):
    """Raise UserError if the current user is in the no-product-create
    group. Skipped for superuser/sudo callers (e.g. demo data, migrations,
    POS combo auto-creates) so the gate doesn't break system flows."""
    if env.su or env.user.id == 1:
        return
    if env.user.has_group(_NO_PRODUCT_CREATE_GROUP_XID):
        raise UserError(_(
            "%(user)s is not allowed to create products. "
            "Please ask a manager.",
            user=env.user.name,
        ))


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    old_item_number = fields.Char(string='Old Item Number', stored=True)
    alternate_item_name = fields.Char(string='Alternate Name', stored=True)
    alternate_unit_of_measure = fields.Many2one(
        'uom.uom',
        string='Alternate Unit of Measure',
        stored=True
    )
    conversion_rate = fields.Integer(string='Conversion Rate', stored=True)
    remarks = fields.Char(string='Remarks', stored=True)
    brand = fields.Char(string='Brand', stored=True)
    net_weight = fields.Char(string='Net Weight', stored=True)
    packing_spec = fields.Char(string='包裝規格')

    @api.model_create_multi
    def create(self, vals_list):
        _hh_block_product_create_for_shop_user(self.env)
        return super().create(vals_list)


class ProductProduct(models.Model):
    _inherit = 'product.product'

    @api.model_create_multi
    def create(self, vals_list):
        _hh_block_product_create_for_shop_user(self.env)
        return super().create(vals_list)

    @api.model
    def name_search(self, name='', args=None, operator='ilike', limit=100):
        """Make Old Item Code (old_item_number) the top-priority match
        in product name_search across the system. Returns
        old_item_number matches first, then falls through to core's
        progressive search (default_code -> barcode -> name etc.) for
        any remaining slots.
        """
        if not name:
            return super().name_search(name=name, args=args, operator=operator, limit=limit)
        from odoo.osv import expression
        base_domain = args or []
        old_matches = self.search_fetch(
            expression.AND([
                base_domain,
                [('old_item_number', operator, name)],
            ]),
            ['display_name'],
            limit=limit,
        )
        rest_limit = (limit or 100) - len(old_matches)
        other_results = []
        if rest_limit > 0:
            exclude_ids = old_matches.ids
            std_args = (
                expression.AND([base_domain, [('id', 'not in', exclude_ids)]])
                if exclude_ids else base_domain
            )
            other_results = super().name_search(
                name=name, args=std_args, operator=operator, limit=rest_limit,
            )
        return [(p.id, p.display_name) for p in old_matches.sudo()] + other_results