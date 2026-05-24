/** @odoo-module **/

import { Component, useState, onWillStart, onMounted, onWillUnmount, useEffect } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const HEARTBEAT_MS = 15_000;
const TRACKED_MODELS = ["sale.order", "purchase.order", "stock.picking"];

class HHEditingBanner extends Component {
    static template = "hh_concurrent_edit_warning.EditingBanner";
    static props = {
        // standard widget props passed by the form view
        record: { type: Object },
        readonly: { type: Boolean, optional: true },
        name: { type: String, optional: true },
        title: { type: String, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.bus = useService("bus_service");
        this.state = useState({ editors: [] });

        // Per-instance bookkeeping so we can clean up cleanly on
        // record-switch and on unmount.
        this._active = { model: null, res_id: null, channel: null };
        this._heartbeatTimer = null;
        this._beforeUnload = null;

        // React to record id / model changes (form view reuses the
        // same component when navigating with the pager).
        useEffect(
            () => {
                this._attach();
                return () => this._detach();
            },
            () => [this.props.record.resModel, this.props.record.resId],
        );

        onMounted(() => {
            // Browser unload: synchronous best-effort unregister so
            // teammates' banners drop immediately when this user
            // closes the tab or navigates away.
            this._beforeUnload = () => {
                if (this._active.res_id) {
                    // navigator.sendBeacon would be ideal but ORM RPC
                    // doesn't expose that. Fire-and-forget regular RPC.
                    this.orm.silent.call(
                        "hh.concurrent.editing",
                        "hh_unregister",
                        [this._active.model, this._active.res_id],
                    );
                }
            };
            window.addEventListener("beforeunload", this._beforeUnload);
        });

        onWillUnmount(() => {
            this._detach();
            if (this._beforeUnload) {
                window.removeEventListener("beforeunload", this._beforeUnload);
                this._beforeUnload = null;
            }
        });
    }

    get visible() {
        return this.state.editors.length > 0;
    }

    get label() {
        const editors = this.state.editors;
        if (editors.length === 0) return "";
        const names = editors.map((e) => e.user_name).join("、");
        const latest = Math.min(...editors.map((e) => e.seconds_ago));
        return `${names} 正在編輯此記錄（最後活動 ${latest} 秒前）`;
    }

    async _attach() {
        const { resModel, resId } = this.props.record;
        if (!TRACKED_MODELS.includes(resModel) || !resId) {
            return;
        }
        this._active = {
            model: resModel,
            res_id: resId,
            channel: `hh.editing:${resModel}:${resId}`,
        };
        this.bus.addChannel(this._active.channel);
        this.bus.subscribe("hh.editing/refresh", this._onBusRefresh.bind(this));

        await this.orm.call("hh.concurrent.editing", "hh_register", [resModel, resId]);
        await this._refresh();

        this._heartbeatTimer = setInterval(async () => {
            if (!this._active.res_id) return;
            await this.orm.silent.call(
                "hh.concurrent.editing",
                "hh_heartbeat",
                [this._active.model, this._active.res_id],
            );
            await this._refresh();
        }, HEARTBEAT_MS);
    }

    async _detach() {
        if (this._heartbeatTimer) {
            clearInterval(this._heartbeatTimer);
            this._heartbeatTimer = null;
        }
        const { model, res_id, channel } = this._active;
        if (channel) {
            this.bus.deleteChannel(channel);
        }
        if (model && res_id) {
            try {
                await this.orm.silent.call(
                    "hh.concurrent.editing",
                    "hh_unregister",
                    [model, res_id],
                );
            } catch (e) {
                // swallow: navigation cleanup, best effort
            }
        }
        this._active = { model: null, res_id: null, channel: null };
        this.state.editors = [];
    }

    _onBusRefresh(payload) {
        if (
            payload &&
            payload.model === this._active.model &&
            payload.res_id === this._active.res_id
        ) {
            this._refresh();
        }
    }

    async _refresh() {
        const { model, res_id } = this._active;
        if (!model || !res_id) return;
        try {
            const editors = await this.orm.silent.call(
                "hh.concurrent.editing",
                "hh_get_editors",
                [model, res_id],
            );
            this.state.editors = editors || [];
        } catch (e) {
            this.state.editors = [];
        }
    }
}

registry.category("view_widgets").add("hh_editing_banner", {
    component: HHEditingBanner,
});
