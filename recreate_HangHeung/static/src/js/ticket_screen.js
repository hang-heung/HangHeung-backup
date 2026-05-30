/** @odoo-module **/

import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
import { patch } from "@web/core/utils/patch";
import { parseUTCString } from "@point_of_sale/utils";

// Match the standard PoS page-size constant (NBR_BY_PAGE = 30 in
// addons/point_of_sale/static/src/app/screens/ticket_screen/ticket_screen.js).
// We can't import it directly so we re-declare. If standard Odoo
// changes this, update here too.
const HH_TICKET_PAGE_SIZE = 30;

patch(TicketScreen.prototype, {
    async onDoRefund() {
        const order = this.getSelectedOrder();
        if (order) {
            this.pos._refund_source_order_id = order.backendId || order.id;
            this.pos._refund_source_order_name = order.name;
        }

        await super.onDoRefund();
    },

    async _setOrder(order) {
        if (order && order.finalized) {
            this.setSelectedOrder(order);
            return;
        }
        await super._setOrder(order);
    },

    onDoFullRefund() {
        const order = this.getSelectedOrder();
        if (!order) return;

        for (const line of order.lines) {
            const refundableQty = line.qty - (line.refunded_qty || 0);
            if (refundableQty <= 0) continue;
            const detail = this.getToRefundDetail(line);
            if (detail.destionation_order_id) continue;
            detail.qty = refundableQty;
        }
        if (this.numberBuffer && this.numberBuffer.reset) {
            this.numberBuffer.reset();
        }
    },

    hasFullRefundCandidates() {
        const order = this.getSelectedOrder();
        if (!order) return false;
        for (const line of order.lines) {
            if ((line.qty - (line.refunded_qty || 0)) > 0) {
                const detail = this.getToRefundDetail(line);
                if (!detail.destionation_order_id) return true;
            }
        }
        return false;
    },

    // Replace standard _fetchSyncedOrders: derive offset
    // deterministically from state.page instead of accumulating into
    // ticketScreenState.offsetByDomain.
    //
    // The standard implementation advances offsetByDomain by
    // ordersInfo.length on every call, but _fetchSyncedOrders is
    // triggered by Mount, Filter-select, Search, Next-page AND
    // Prev-page. So clicking Prev/Filter/etc. silently advances the
    // offset, and subsequent fetches skip middle pages -- the user
    // sees gaps in the order list (e.g. records 30-90 invisible
    // while 0-29 and 90+ are present). Computing offset from
    // state.page keeps fetch and the in-memory slice perfectly
    // aligned with the on-screen page number.
    async _fetchSyncedOrders() {
        const screenState = this.pos.ticketScreenState;
        const domain = this._computeSyncedOrdersDomain();
        const config_id = this.pos.config.id;
        const offset = ((this.state.page || 1) - 1) * HH_TICKET_PAGE_SIZE;
        const { ordersInfo, totalCount } = await this.pos.data.call(
            "pos.order",
            "search_paid_order_ids",
            [],
            {
                config_id,
                domain,
                limit: HH_TICKET_PAGE_SIZE,
                offset,
            }
        );

        screenState.totalCount = totalCount;

        const idsNotInCacheOrOutdated = ordersInfo
            .filter((orderInfo) => {
                const order = this.pos.models["pos.order"].get(orderInfo[0]);
                if (order && parseUTCString(orderInfo[1]) > parseUTCString(order.date_order)) {
                    return true;
                }
                return !order;
            })
            .map((info) => info[0]);

        if (idsNotInCacheOrOutdated.length > 0) {
            await this.pos.data.read("pos.order", Array.from(new Set(idsNotInCacheOrOutdated)));
        }
    },
});
