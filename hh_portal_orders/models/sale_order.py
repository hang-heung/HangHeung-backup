from odoo import _, api, fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # HH-PORTAL: marks a sale.order created from the /my/upload-sales
    # portal page (上載購物紀錄). These orders represent records of
    # consignment sales already made by the consignee, so they:
    #   * skip outgoing picking creation entirely (consignee already has
    #     the goods from a prior 訂貨單)
    #   * still get an invoice created and posted in the backend
    is_portal_record_upload = fields.Boolean(
        string='Portal: Record Upload',
        default=False,
        copy=False,
        readonly=True,
        index=True,
        help="True when this SO was generated from the consignee's "
             "上載購物紀錄 portal page. Picking creation is skipped; "
             "an invoice is created and posted on confirmation.",
    )

    is_portal_customer_order = fields.Boolean(
        string='Portal: Customer Order',
        default=False,
        copy=False,
        readonly=True,
        index=True,
        help="True when this SO was placed by a HangHeung consignee "
             "via the 客戶訂貨單 portal page.",
    )

    def _action_confirm(self):
        # Portal record-upload SOs have no delivery, but commitment_date
        # is required by HH backend UX (otherwise the form refuses to
        # close). Set it to the order date so the field is populated
        # without implying a real ship date.
        for so in self.filtered(lambda o: o.is_portal_record_upload and not o.commitment_date):
            so.commitment_date = so.date_order
        result = super()._action_confirm()
        for so in self.filtered('is_portal_record_upload'):
            so._hh_create_record_upload_invoice()
        return result

    # ------------------------------------------------------------------
    # Bypass the HH pre-order constraints for portal record-upload SOs.
    # A 上載購物紀錄 SO has no delivery, so partner_shipping_id and
    # commitment_date don't apply.
    # ------------------------------------------------------------------

    def _check_pre_order_required_fields(self):
        normal = self.filtered(lambda o: not o.is_portal_record_upload)
        return super(SaleOrder, normal)._check_pre_order_required_fields()

    def _check_commitment_date_min_lead(self):
        normal = self.filtered(lambda o: not o.is_portal_record_upload)
        return super(SaleOrder, normal)._check_commitment_date_min_lead()

    def _hh_create_record_upload_invoice(self):
        """Create a DRAFT invoice on a record-upload SO. Forces invoiceable
        qty to product_uom_qty so the call works even when the product's
        invoice_policy is 'delivery' (no delivery has happened for these
        SOs by design).

        The invoice is intentionally left in DRAFT: a portal action should
        not post directly to the GL. Back-office reviews and posts it.
        """
        self.ensure_one()
        if not self.order_line:
            return
        return self.with_context(hh_force_order_invoice=True).sudo()._create_invoices()


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    @api.depends('qty_invoiced', 'qty_delivered', 'product_uom_qty', 'state',
                 'order_id.is_portal_record_upload')
    def _compute_qty_to_invoice(self):
        """When the SO is a portal record-upload, treat every line as
        ready to invoice based on the ordered qty regardless of the
        product's invoice_policy. Goods never move (consignee already
        holds them) so the delivery-policy path would always show
        qty_to_invoice = 0."""
        super()._compute_qty_to_invoice()
        for line in self:
            order = line.order_id
            if (
                order.is_portal_record_upload
                and line.state == 'sale'
                and not line.display_type
            ):
                line.qty_to_invoice = line.product_uom_qty - line.qty_invoiced

    def _action_launch_stock_rule(self, previous_product_uom_qty=False):
        """Skip procurement / picking creation for portal record-upload
        SO lines -- the consignee already has the goods, nothing to
        ship."""
        lines = self.filtered(lambda l: not l.order_id.is_portal_record_upload)
        if not lines:
            return True
        return super(SaleOrderLine, lines)._action_launch_stock_rule(
            previous_product_uom_qty=previous_product_uom_qty,
        )
