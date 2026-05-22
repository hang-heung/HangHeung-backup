{
    'name': 'POS Inter-Company Picking Fix',
    'version': '18.0.1.0.0',
    'summary': 'Fixes stock.picking access error for inter-company routes in POS',
    'description': """
        When a POS cashier processes payment for products with inter-company stock routes,
        Odoo's procurement engine traverses all routes including cross-company ones.
        Users restricted to a single company receive an access error on stock.picking.

        This module overrides _create_order_picking() to run in sudo() context,
        allowing the picking creation to traverse inter-company routes without
        changing any user-facing permissions.

        Fully reversible by uninstalling.
    """,
    'author': 'Custom',
    'category': 'Point of Sale',
    'depends': ['point_of_sale', 'stock'],
    'data': [],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
