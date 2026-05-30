/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { Navbar } from "@point_of_sale/app/navbar/navbar";

patch(Navbar.prototype, {
    hhOnContactSearchKeydown(ev) {
        if (ev.key !== "Enter") {
            return;
        }
        const query = (ev.target.value || "").trim();
        ev.target.value = "";
        if (query) {
            this.pos.hhSelectPartnerWithQuery(query);
        }
    },
});
