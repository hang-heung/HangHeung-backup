# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': 'Hang Heung Customizations',
    'version': '1.0.53',
    'summary': 'Includes all Hang Heung customizations',
    'description': """
        This module contains all of Hang Heung customizations.
    """,
    'author': 'Lau Siu Hin',
    'website': '',
    'depends': ['contacts', 'base', 'stock', 'web', 'purchase', 'point_of_sale', 'sale_purchase_inter_company_rules', 'account'],
    'data': [
        "security/ir.model.access.csv",
        "security/pos_group.xml",
        "security/sales_non_sales_groups.xml",
        "security/role_groups.xml",
        "security/wedding_chain_rule.xml",
        "views/res_partner.xml",
        "views/customer_category_data.xml",
        "views/res_users.xml",
        "views/product_template.xml",
        "views/stock_picking_view.xml",
        "views/reason_code_views.xml",
        "views/pos_payment_method.xml",
        "views/delivery_slip_report_inherit.xml",
        "wizard/wizard_open.xml",
        "views/purchase_order_view.xml",
        # "views/custom_backorder.xml",
        "views/purchase_order_report_inherit.xml",
        "views/external_layout_standard_inherit.xml",
        "views/sale_order_view.xml",
        "views/account_move_views_inherit.xml",
        "views/inventory_list_default_order.xml",
        "views/sale_purchase_list_default_order.xml",
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'recreate_HangHeung/static/src/js/*',
            'recreate_HangHeung/static/src/xml/*',
        ],
    },

    'installable': True,
    'application': False,
    'auto_install': False,
}
