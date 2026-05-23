/** @odoo-module */

import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";
import { patch } from "@web/core/utils/patch";

patch(OrderReceipt.prototype, {
    /**
     * Total quantity of real items on the receipt.
     * Excludes: refund lines (qty <= 0) and discount/promotion lines
     * identified by a negative total price string (e.g. "569X3.00").
     */
    get totalCartQty() {
        const lines = this.props.data.orderlines;
        if (!lines?.length) return 0;
        return lines.reduce((sum, line) => {
            const n = parseFloat(line.qty);
            if (isNaN(n) || n <= 0) return sum;                // skip refund lines
            if (String(line.price || "").includes("-")) return sum;  // skip discount lines
            return sum + n;
        }, 0);
    },
});
