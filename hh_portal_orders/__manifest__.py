# -*- coding: utf-8 -*-
{
    'name': 'HangHeung Portal Orders',
    'version': '1.3.15',
    'summary': 'Customer portal for record-upload (上載購物紀錄) and order placement (訂貨單)',
    'description': """
        Adds two portal pages for external consignee customers:
        - /my/upload-sales (上載購物紀錄): consignee reports past sales,
          creates a Hoymay SO with no delivery, invoice in backend.
        - /my/place-order (訂貨單): consignee orders fresh stock,
          triggers the existing Hoymay -> That's -> HangHeung
          intercompany chain with dropship delivery.

        A backend model 'portal.order.control' (Sales menu) maintains a
        per-customer pricelist and allowed-product list. Each portal
        partner has one record; the portal pages render only that
        partner's allowed products.
    """,
    'author': 'HangHeung IT',
    'depends': [
        'sale_management',
        'portal',
        'point_of_sale',  # for pos_categ_ids on product.template
        'recreate_HangHeung',  # commitment_date + intercompany chain glue + alternate_unit_of_measure/conversion_rate
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/portal_security.xml',
        'views/portal_order_control_views.xml',
        'views/portal_templates.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
