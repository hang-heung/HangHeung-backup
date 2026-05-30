{
    'name': 'Hang Heung POS Navbar',
    'version': '1.0.1',
    'category': 'Point of Sale',
    'summary': 'POS top bar: company logo in the middle + contact search to its left',
    'author': 'Lau Siu Hin',
    'depends': ['point_of_sale'],
    'data': [],
    'assets': {
        'point_of_sale._assets_pos': [
            'hh_pos_navbar/static/src/js/pos_store.js',
            'hh_pos_navbar/static/src/js/partner_list.js',
            'hh_pos_navbar/static/src/js/navbar.js',
            'hh_pos_navbar/static/src/xml/navbar.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
