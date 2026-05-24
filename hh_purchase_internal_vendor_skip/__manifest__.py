{
    "name": "HH Purchase Internal Vendor Skip",
    "version": "18.0.1.0.0",
    "summary": "Skip _add_supplier_to_product when the PO vendor is the internal intercompany vendor and is already linked to all line products.",
    "description": """
HH Purchase Internal Vendor Skip
=================================
On PO confirmation, standard Odoo calls _add_supplier_to_product, which writes
a new product.supplierinfo row for each (vendor, product) pairing that doesn't
already exist. This write touches product_template / product_product rows and
is a major source of Postgres SerializationFailure when multiple staff confirm
POs to the same internal intercompany vendor (id 8883, "That's Ltd")
concurrently.

For vendor 8883 specifically, all currently-used products are already linked
as sellers (verified 120/120 on production at install time). The write is
therefore a no-op for the common case but creates lock contention every time.

This override skips the call only when EVERY line product on the PO already
has vendor 8883 as a registered seller. Brand-new (vendor, product) pairings
still go through the standard write path so supplierinfo continues to be
auto-created when actually needed.

Affects vendor id 8883 only. All other vendors retain standard behaviour.
""",
    "author": "Hang Heung internal",
    "license": "LGPL-3",
    "category": "Purchases",
    "depends": ["purchase"],
    "data": [],
    "installable": True,
    "auto_install": False,
    "application": False,
}
