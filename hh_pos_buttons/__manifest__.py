{
    'name': 'Hang Heung POS Buttons',
    'version': '1.0.0',
    'category': 'Point of Sale',
    'summary': 'Hide General/Customer/Internal Note buttons in POS',
    'author': 'Lau Siu Hin',
    'depends': ['point_of_sale'],
    'data': [],
    'assets': {
        'point_of_sale._assets_pos': [
            'hh_pos_buttons/static/src/xml/control_buttons.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
