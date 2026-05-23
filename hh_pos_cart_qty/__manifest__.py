# -*- coding: utf-8 -*-
{
    'name': 'HH POS Cart Qty Badges',
    'version': '18.0.1.1.0',
    'category': 'Point Of Sale',
    'summary': 'Show total cart quantity (screen + receipt) and per-category quantity badges in POS',
    'author': 'HangHeung',
    'depends': ['point_of_sale'],
    'assets': {
        'point_of_sale._assets_pos': [
            'hh_pos_cart_qty/static/src/xml/order_widget_patch.xml',
            'hh_pos_cart_qty/static/src/xml/category_selector_patch.xml',
            'hh_pos_cart_qty/static/src/xml/order_receipt_patch.xml',
            'hh_pos_cart_qty/static/src/js/order_widget_patch.js',
            'hh_pos_cart_qty/static/src/js/category_selector_patch.js',
            'hh_pos_cart_qty/static/src/js/order_receipt_patch.js',
            'hh_pos_cart_qty/static/src/css/pos_cart_qty.css',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': False,
}
