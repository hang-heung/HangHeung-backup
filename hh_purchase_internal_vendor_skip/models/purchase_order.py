from odoo import models

# Hard-coded to match recreate_HangHeung/purchase.py:get_default_vendor,
# which also hard-codes 8883 as the company-1 default vendor. If the
# intercompany vendor partner id ever changes (e.g. after a DB migration),
# both places must be updated together.
INTERNAL_INTERCOMPANY_VENDOR_ID = 8883


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    def _add_supplier_to_product(self):
        """Skip the supplierinfo auto-create write when all line products
        already have the internal intercompany vendor (8883) registered
        as a seller.

        Rationale: standard _add_supplier_to_product writes
        product.supplierinfo via product_template.write({seller_ids: ...}),
        which touches product_template / product_product rows. With multiple
        staff confirming POs to vendor 8883 concurrently and heavily overlapping
        product lines, this is the dominant source of Postgres
        SerializationFailure ("could not serialize access due to concurrent
        update") in the purchase workflow.

        We only skip when the write would be a no-op anyway -- i.e. every
        line product already has 8883 in its seller_ids. Brand-new
        (vendor, product) pairings still flow through super() so the
        standard auto-link continues to fire when it actually has work to do.
        """
        # Split self into "safe to skip" vs "must run standard logic".
        # A PO is safe to skip when:
        #   - its vendor is the internal intercompany vendor (8883), AND
        #   - every line product already has that vendor in seller_ids.
        skip_ids = []
        for po in self:
            if po.partner_id.id != INTERNAL_INTERCOMPANY_VENDOR_ID:
                continue
            all_linked = True
            for line in po.order_line:
                if not line.product_id:
                    continue
                seller_partner_ids = line.product_id.seller_ids.mapped("partner_id").ids
                if INTERNAL_INTERCOMPANY_VENDOR_ID not in seller_partner_ids:
                    all_linked = False
                    break
            if all_linked:
                skip_ids.append(po.id)

        if skip_ids:
            remaining = self - self.browse(skip_ids)
        else:
            remaining = self

        if remaining:
            return super(PurchaseOrder, remaining)._add_supplier_to_product()
        return None
