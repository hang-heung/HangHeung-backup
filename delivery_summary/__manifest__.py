# -*- coding: utf-8 -*-
{
    'name': 'Delivery Summary Report',
    'version': '18.0.1.0.0',
    'summary': 'Delivery Summary Report (actual delivered qty)',
    'category': 'Reporting',
    'description': 'Excel report showing actual delivered quantities per product per shop, based on validated stock move lines.',
    'depends': ['base', 'stock'],
    'data': [
        'security/ir.model.access.csv',
        'views/menu_views.xml',
        'wizard/delivery_wizard_views.xml',
    ],
    'installable': True,
    'application': True,
}
