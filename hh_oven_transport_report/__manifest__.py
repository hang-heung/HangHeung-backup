# -*- coding: utf-8 -*-
{
    'name': 'HH Oven & Transport Picking Sheets',
    'version': '18.0.1.0.0',
    'summary': """運輸執貨紙 & 燒爐紙 reports for H01 酥餅 category""",
    'category': 'Reporting',
    'description': """Generates the 運輸執貨紙 (transport picking) and 燒爐紙 (oven)
    Excel reports for the H01 酥餅 category. Quantities are divided by the numeric
    part of the product packing_spec field, except products whose name contains
    (6件) which keep their raw quantity.""",
    'depends': ['base', 'stock'],
    'data': [
        'security/ir.model.access.csv',
        'wizard/oven_transport_wizard_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': False,
}
