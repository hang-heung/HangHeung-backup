# -*- coding: utf-8 -*-
{
    'name': 'HH POS Sales Details Report',
    'version': '18.0.1.0.0',
    'summary': 'Customises POS Sales Details report for Hang Heung',
    'depends': ['point_of_sale', 'pos_hr'],
    'data': ['views/report_saledetails_inherit.xml', 'views/pos_details_wizard_inherit.xml'],
    'external_dependencies': {'python': ['xlsxwriter']},
    'installable': True,
    'auto_install': False,
}
