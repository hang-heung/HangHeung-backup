/** @odoo-module */

import { CategorySelector } from "@point_of_sale/app/generic_components/category_selector/category_selector";
import { patch } from "@web/core/utils/patch";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { onMounted } from "@odoo/owl";

patch(CategorySelector.prototype, {
    setup() {
        super.setup();
        this.pos = usePos();

        onMounted(() => {
            const settings = this.pos.models["sh.pos.theme.settings"]?.getAll()?.[0];
            const color = settings?.primary_color || "#ff0000";
            document.documentElement.style.setProperty("--hh-pos-primary", color);
        });
    },

    /**
     * Returns true if the line is a goods line (not a promo/service).
     * Mirrors the filter used in custom_pos_receipt.
     */
    _isGoodsLine(line) {
        return !line.is_reward_line && line.product_id?.type !== "service";
    },

    /**
     * Mark 2: Total quantity of GOODS in a category (incl. sub-categories).
     */
    getCategoryCartQty(categoryId) {
        const order = this.pos.get_order();
        if (!order || !order.lines?.length) return 0;

        const category = this.pos.models["pos.category"]
            .getAll()
            .find((c) => c.id === categoryId);
        if (!category) return 0;

        const allCategoryIds = new Set(category.getAllChildren().map((c) => c.id));

        const productIds = new Set();
        for (const catId of allCategoryIds) {
            const products =
                this.pos.models["product.product"].getBy("pos_categ_ids", catId) || [];
            const arr = Array.isArray(products) ? products : [products];
            for (const p of arr) {
                if (p?.id != null) productIds.add(p.id);
            }
        }

        return order.lines.reduce((total, line) => {
            if (this._isGoodsLine(line) && productIds.has(line.product_id?.id)) {
                return total + (line.qty || 0);
            }
            return total;
        }, 0);
    },
});
