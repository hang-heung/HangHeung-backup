/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/store/pos_store";

patch(PosStore.prototype, {
    async setup() {
        await super.setup(...arguments);
        this.hhMemberRules = [];
        this.hhMemberProgress = {};
        try {
            this.hhMemberRules = await this.data.call(
                "hh.member.free.rule", "get_pos_rules", []
            );
        } catch {
            this.hhMemberRules = [];
        }
    },

    async selectPartner(partner) {
        const res = await super.selectPartner(...arguments);
        const order = this.get_order();
        await this.hhLoadMemberProgress(order && order.get_partner());
        return res;
    },

    async hhLoadMemberProgress(partner) {
        this.hhMemberProgress = {};
        if (!partner) {
            return;
        }
        try {
            this.hhMemberProgress = await this.data.call(
                "hh.member.free.progress", "get_progress_for_pos", [partner.id]
            );
        } catch {
            this.hhMemberProgress = {};
        }
    },

    /**
     * For the current order, return [{rule, offerable}] where `offerable` is
     * how many more free gifts can be added now, combining the member's
     * carried-over balance with qualifying units already in the cart.
     */
    hhComputeFreeOffers(order) {
        const offers = [];
        if (!order) {
            return offers;
        }
        const partner = order.get_partner();
        if (!partner) {
            return offers;
        }
        const progress = this.hhMemberProgress || {};
        for (const rule of this.hhMemberRules || []) {
            const qualSet = new Set(rule.qualifying_product_ids);
            let cartQual = 0;
            let freeInCart = 0;
            for (const line of order.lines) {
                const ruleRef = line.hh_member_free_rule_id;
                if (ruleRef) {
                    if (ruleRef === rule.id) {
                        freeInCart += line.get_quantity();
                    }
                    continue;
                }
                const prod = line.product_id;
                if (prod && qualSet.has(prod.id) && line.get_quantity() > 0) {
                    cartQual += line.get_quantity();
                }
            }
            const entry = progress[rule.id] || {};
            const carried = entry.accumulated_qty || 0;
            const grants = entry.grant_count || 0;
            let freeDue = Math.floor((carried + cartQual) / rule.threshold_qty);
            if (rule.once_per_member) {
                freeDue = Math.min(freeDue, Math.max(0, 1 - grants));
            }
            const offerable = freeDue - freeInCart;
            if (offerable > 0) {
                offers.push({ rule, offerable });
            }
        }
        return offers;
    },
});
