/** @odoo-module **/
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { SelectionPopup } from "@point_of_sale/app/utils/input_popups/selection_popup";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

patch(ControlButtons.prototype, {
    hhGetFreeOffers() {
        return this.pos.hhComputeFreeOffers(this.pos.get_order());
    },

    async hhClickFreeGift() {
        const order = this.pos.get_order();
        if (!order || !order.get_partner()) {
            this.notification.add(_t("請先選擇會員（客戶）。"), { type: "warning" });
            return;
        }
        const offers = this.hhGetFreeOffers();
        if (!offers.length) {
            this.notification.add(
                _t("此會員暫未符合任何免費贈品優惠（累積數量未達標、或已達每人一次上限）。"),
                { type: "warning" }
            );
            return;
        }

        // Choose which rule, if more than one is currently eligible.
        let offer = offers[0];
        if (offers.length > 1) {
            const picked = await makeAwaitable(this.dialog, SelectionPopup, {
                title: _t("選擇會員優惠"),
                list: offers.map((o) => ({
                    id: o.rule.id,
                    item: o,
                    label: o.rule.name,
                })),
            });
            if (!picked) {
                return;
            }
            offer = picked;
        }
        const rule = offer.rule;

        // Resolve the gift product (let the cashier pick when several).
        const giftProducts = (rule.gift_product_ids || [])
            .map((id) => this.pos.models["product.product"].get(id))
            .filter(Boolean);
        if (!giftProducts.length) {
            return;
        }
        let giftProduct = giftProducts[0];
        if (giftProducts.length > 1) {
            const picked = await makeAwaitable(this.dialog, SelectionPopup, {
                title: _t("選擇免費贈品"),
                list: giftProducts.map((p) => ({
                    id: p.id,
                    item: p,
                    label: p.display_name,
                })),
            });
            if (!picked) {
                return;
            }
            giftProduct = picked;
        }

        await this.pos.addLineToCurrentOrder(
            { product_id: giftProduct, qty: 1, hh_member_free_rule_id: rule.id },
            {}
        );
        const line = order.get_selected_orderline();
        if (line) {
            // Zero the value: full discount = "minus the product value".
            line.set_discount(100);
        }
    },
});
