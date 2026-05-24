{
    "name": "HH Concurrent Edit Warning",
    "version": "18.0.1.0.0",
    "summary": "Soft-lock banner that warns staff when another user is currently editing the same Sale Order, Purchase Order, Delivery, or Receipt.",
    "description": """
HH Concurrent Edit Warning
==========================
Adds a non-blocking yellow banner to the top of the form view for:
  - sale.order
  - purchase.order
  - stock.picking (deliveries, receipts, internal transfers)

The banner appears within ~1 second when another user opens the same record,
and disappears within ~15 seconds when they close it. It is a warning only:
it does not block edits.

Mechanism: each open form posts a heartbeat to the server every 15 seconds.
The server broadcasts presence over the bus so other open clients see live
updates without polling. Stale rows are pruned by a daily cron.
""",
    "author": "Hang Heung internal",
    "license": "LGPL-3",
    "category": "Tools",
    "depends": ["base", "bus", "web", "sale", "purchase", "stock"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "views/sale_order_views.xml",
        "views/purchase_order_views.xml",
        "views/stock_picking_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "hh_concurrent_edit_warning/static/src/widgets/editing_banner.js",
            "hh_concurrent_edit_warning/static/src/widgets/editing_banner.xml",
            "hh_concurrent_edit_warning/static/src/widgets/editing_banner.scss",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": False,
}
