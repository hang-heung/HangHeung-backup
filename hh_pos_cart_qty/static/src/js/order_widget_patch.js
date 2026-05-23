/** @odoo-module */

import { OrderWidget } from "@point_of_sale/app/generic_components/order_widget/order_widget";
import { patch } from "@web/core/utils/patch";
import { usePos } from "@point_of_sale/app/store/pos_hook";

patch(OrderWidget.prototype, {
    setup() {
        super.setup();
        this.pos = usePos();
    },

    /**
     * Mark 1: Total quantity of GOODS in the current POS cart.
     * Uses the same filter as custom_pos_receipt:
     *   - exclude reward/promo lines (is_reward_line)
     *   - exclude service-type products (discount products, tips, gift cards)
     */
    get totalCartQty() {
        if (!this.props.lines?.length) return 0;
        return this.props.lines.reduce((sum, line) => {
            if (!line.is_reward_line && line.product_id?.type !== "service") {
                return sum + (line.qty || 0);
            }
            return sum;
        }, 0);
    },
});
