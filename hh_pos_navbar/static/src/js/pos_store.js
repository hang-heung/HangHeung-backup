/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { PartnerList } from "@point_of_sale/app/screens/partner_list/partner_list";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";

patch(PosStore.prototype, {
    /**
     * Open the native customer-selection screen pre-filtered by `query`,
     * and set the chosen partner on the current order.
     */
    async hhSelectPartnerWithQuery(query) {
        const order = this.get_order();
        if (!order) {
            return;
        }
        const currentPartner = order.get_partner();
        const payload = await makeAwaitable(this.dialog, PartnerList, {
            partner: currentPartner,
            hhInitialQuery: query || "",
            getPayload: (newPartner) => order.set_partner(newPartner),
        });
        if (payload) {
            order.set_partner(payload);
        }
    },
});
