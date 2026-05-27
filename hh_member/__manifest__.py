{
    'name': 'Hang Heung Member',
    'version': '1.0.1',
    'category': 'Point of Sale',
    'summary': 'HangHeung membership tiers (Hoymay only)',
    'description': """
        Membership tier mechanism for HangHeung. Configurable via a tier
        table (name, min_spending, pricelist, earn_rate, redeem_value, tag).
        Spending counted on Hoymay POS orders in the trailing 365 days.
        A 5-minute cron re-evaluates partners; pos.order.action_pos_order_paid
        also triggers re-evaluation for paid Hoymay orders.
    """,
    'author': 'Lau Siu Hin',
    'website': '',
    'depends': ['base', 'contacts', 'point_of_sale', 'product'],
    'data': [
        'security/ir.model.access.csv',
        'data/hh_member_tier_data.xml',
        'data/ir_cron.xml',
        'views/hh_member_tier_views.xml',
        'views/res_partner_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
}
