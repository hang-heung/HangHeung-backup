from odoo import models, fields, api


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    # Stored as a plain Integer (the rule's id) rather than a Many2one so the
    # POS frontend can set/round-trip it without loading hh.member.free.rule
    # as a POS model. 0 / False = a normal line.
    hh_member_free_rule_id = fields.Integer(
        string='會員免費贈品規則',
        default=0,
        help="Rule id of the buy-X-get-free gift line (0 for normal lines).",
    )

    @api.model
    def _load_pos_data_fields(self, config_id):
        fields_list = super()._load_pos_data_fields(config_id)
        if 'hh_member_free_rule_id' not in fields_list:
            fields_list.append('hh_member_free_rule_id')
        return fields_list
