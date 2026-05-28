{
    'name': 'Hang Heung Member',
    'version': '1.0.7',
    'category': 'Point of Sale',
    'summary': 'HangHeung membership tiers + buy-X-get-free (Hoymay only)',
    'description': """
        Membership mechanism for HangHeung (Hoymay company only):

        1. Membership tiers — configurable table (name, min_spending,
           pricelist, earn_rate, redeem_value, tag). Spending counted on
           Hoymay POS orders in the trailing 365 days. A 5-minute cron
           re-evaluates partners; the paid-order hook re-evaluates too.

        2. Buy-X-get-free — configurable rules (qualifying products /
           categories, threshold qty, free product). Members accumulate
           qualifying units across transactions; on each threshold cross,
           a free-product coupon is issued (native loyalty coupon, applied
           in POS) and the counter resets.
    """,
    'author': 'Lau Siu Hin',
    'website': '',
    'depends': ['base', 'contacts', 'point_of_sale', 'product', 'loyalty', 'pos_loyalty'],
    'data': [
        'security/ir.model.access.csv',
        'data/hh_member_tier_data.xml',
        'data/ir_cron.xml',
        'views/hh_member_tier_views.xml',
        'views/hh_member_free_rule_views.xml',
        'views/res_partner_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
}
