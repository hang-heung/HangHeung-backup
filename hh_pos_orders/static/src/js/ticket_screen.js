/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";

patch(TicketScreen.prototype, {
    /**
     * Comma-separated list of unique payment-method names on the order.
     * Handles mixed-payment orders (multiple payment_ids).
     */
    getPaymentMethods(order) {
        if (!order || !order.payment_ids || !order.payment_ids.length) {
            return "";
        }
        const names = order.payment_ids
            .map((p) => p.payment_method_id && p.payment_method_id.name)
            .filter(Boolean);
        return [...new Set(names)].join(", ");
    },
});
