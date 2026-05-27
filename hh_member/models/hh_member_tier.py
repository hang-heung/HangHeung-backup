from odoo import models, fields, api

HOYMAY_COMPANY_ID = 1


class HHMemberTier(models.Model):
    _name = 'hh.member.tier'
    _description = '會員等級配置'
    _order = 'min_spending desc, id'

    name = fields.Char(string='會員等級', required=True)
    min_spending = fields.Monetary(
        string='365天最低消費 (HKD)',
        required=True,
        currency_field='currency_id',
    )
    pricelist_id = fields.Many2one(
        'product.pricelist',
        string='適用價格表',
        required=True,
        ondelete='restrict',
    )
    earn_rate = fields.Float(
        string='賺取比率 (每 X 元 = 1 點)',
        required=True,
        default=1.0,
        help="HKD spent per 1 loyalty point earned. Higher value = harder to earn.",
    )
    redeem_value = fields.Float(
        string='兌換價值 (1 點 = X 元)',
        required=True,
        default=1.0,
        help="HKD value of 1 loyalty point when redeemed.",
    )
    tag_id = fields.Many2one(
        'res.partner.category',
        string='會員標籤',
        required=True,
        ondelete='restrict',
        help="Tag stamped on the partner when assigned to this tier. "
             "Each tier must use a distinct tag.",
    )
    company_id = fields.Many2one(
        'res.company',
        string='公司',
        required=True,
        default=lambda self: self.env['res.company'].browse(HOYMAY_COMPANY_ID),
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
        store=True,
        readonly=True,
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('unique_tag_per_company',
         'unique(tag_id, company_id)',
         '每個會員標籤只能對應一個會員等級。'),
    ]

    @api.constrains('min_spending')
    def _check_min_spending(self):
        for rec in self:
            if rec.min_spending < 0:
                from odoo.exceptions import ValidationError
                raise ValidationError("最低消費必須 >= 0。")
