/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";

patch(PosOrderline.prototype, {
    getDisplayData() {
        return {
            ...super.getDisplayData(...arguments),
            hhMemberFree: !!this.hh_member_free_rule_id,
        };
    },
});
