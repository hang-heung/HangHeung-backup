/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/store/pos_store";

patch(PosStore.prototype, {
    /**
     * Mark the partner-edit action as opened from the POS so the inherited
     * form view can selectively hide non-essential fields.
     */
    editPartnerContext(partner) {
        return {
            ...super.editPartnerContext(...arguments),
            from_pos: true,
        };
    },
});
