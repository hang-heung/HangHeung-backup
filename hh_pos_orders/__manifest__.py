{
    'name': 'Hang Heung POS Orders List',
    'version': '1.0.0',
    'category': 'Point of Sale',
    'summary': 'POS Orders (TicketScreen) list: add a Payment Method column',
    'author': 'Lau Siu Hin',
    'depends': ['point_of_sale'],
    'data': [],
    'assets': {
        'point_of_sale._assets_pos': [
            'hh_pos_orders/static/src/js/ticket_screen.js',
            'hh_pos_orders/static/src/xml/ticket_screen.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
