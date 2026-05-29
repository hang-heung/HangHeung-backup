{
    'name': 'Hang Heung Member',
    'version': '1.1.0',
    'category': 'Point of Sale',
    'summary': 'HangHeung membership tiers + buy-X-get-free (Hoymay only)',
    'description': """
        Membership mechanism for HangHeung (Hoymay company only):

        1. Membership tiers — configurable table (name, min_spending,
           pricelist, earn_rate, redeem_value, tag). Spending counted on
           Hoymay POS orders in the trailing 365 days. A 5-minute cron
           re-evaluates partners; the paid-order hook re-evaluates too.

        2. Buy-X-get-free (會員優惠) — configurable rules (qualifying products
           / categories, threshold qty, free products / category, once per
           member). Members accumulate qualifying units across transactions
           AND within the current cart; when the running total crosses the
           threshold, the POS offers a free gift line ($0 via 100% discount).
           The carried balance is reconciled on payment. No loyalty coupons.
    """,
    'author': 'Lau Siu Hin',
    'website': '',
    'depends': ['base', 'contacts', 'point_of_sale', 'product'],
    'data': [
        'security/ir.model.access.csv',
        'data/hh_member_tier_data.xml',
        'data/ir_cron.xml',
        'views/hh_member_tier_views.xml',
        'views/hh_member_free_rule_views.xml',
        'views/res_partner_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'hh_member/static/src/js/pos_store.js',
            'hh_member/static/src/js/control_buttons.js',
            'hh_member/static/src/xml/control_buttons.xml',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
}
