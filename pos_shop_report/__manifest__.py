# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': 'Hang Heung Shop Reports Customizations',
    'version': '1.1.17',
    'summary': 'Includes all Hang Heung customizations',
    'description': """
        This module contains all of Hang Heung customizations.
    """,
    'author': 'Lau Siu Hin',
    'website': '',
    'depends': ['contacts', 'base', 'stock', 'web', 'purchase','recreate_HangHeung'],
    'data': [
        "security/ir.model.access.csv",
        "wizards/pos_shop_report_wizard.xml",
        "wizards/sales_report.xml",
        "wizards/sales_report_all_shops.xml",
        "wizards/product_sales_detail_report.xml",
        "wizards/product_sales_detail_report_all.xml",
        "wizards/time_period_sales_report_individual.xml",
        "wizards/time_period_sales_report_all.xml",
        "wizards/daily_product_sales_inventory_report.xml",
        "wizards/store_transaction_detail.xml",
        "wizards/coupon_gift_voucher_report.xml",
        "wizards/scrap_report.xml",
        "wizards/internal_transfer_report.xml",
        "wizards/delivery_report_wizard.xml",
        "wizards/po_report_wizard.xml",
        "wizards/reason_code_report.xml",
        "views/pos_shop_report.xml",
        "reports/pos_shop_report.xml",
        "reports/pos_shop_report_format.xml",
        "reports/sales_report_pdf.xml",
        "reports/sales_report_all_shops_pdf.xml",
    ],

    'installable': True,
    'application': False,
    'auto_install': False,
}
