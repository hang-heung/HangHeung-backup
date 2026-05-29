from odoo import models, fields, api


class HHMemberFreeProgress(models.Model):
    _name = 'hh.member.free.progress'
    _description = '會員優惠進度'
    _order = 'partner_id, rule_id'

    partner_id = fields.Many2one(
        'res.partner', required=True, ondelete='cascade', index=True)
    rule_id = fields.Many2one(
        'hh.member.free.rule', required=True, ondelete='cascade', index=True)
    accumulated_qty = fields.Integer(
        string='累積數量', default=0,
        help="Qualifying units carried over toward the next free product "
             "(after past grants).")
    threshold_qty = fields.Integer(
        related='rule_id.threshold_qty', string='所需數量', readonly=True)
    grant_count = fields.Integer(string='已贈送次數', default=0)
    last_grant_date = fields.Datetime(string='最近贈送時間', readonly=True)

    _sql_constraints = [
        ('unique_partner_rule',
         'unique(partner_id, rule_id)',
         '每位會員每條規則只可有一筆進度記錄。'),
    ]

    @api.model
    def _get_or_create(self, partner, rule):
        rec = self.sudo().search([
            ('partner_id', '=', partner.id),
            ('rule_id', '=', rule.id),
        ], limit=1)
        if not rec:
            rec = self.sudo().create({
                'partner_id': partner.id,
                'rule_id': rule.id,
            })
        return rec

    @api.model
    def get_progress_for_pos(self, partner_id):
        """Return {rule_id: {accumulated_qty, grant_count}} for a partner —
        called by the POS frontend when a customer is selected."""
        if not partner_id:
            return {}
        recs = self.sudo().search([('partner_id', '=', partner_id)])
        return {
            r.rule_id.id: {
                'accumulated_qty': r.accumulated_qty,
                'grant_count': r.grant_count,
            }
            for r in recs
        }
