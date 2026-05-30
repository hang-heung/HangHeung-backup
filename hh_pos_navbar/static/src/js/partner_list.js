/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { PartnerList } from "@point_of_sale/app/screens/partner_list/partner_list";

// Allow an optional initial search term to be passed in.
PartnerList.props = {
    ...PartnerList.props,
    hhInitialQuery: { type: String, optional: true },
};

patch(PartnerList.prototype, {
    setup() {
        super.setup(...arguments);
        if (this.props.hhInitialQuery) {
            this.state.query = this.props.hhInitialQuery;
            // Fetch server-side matches too (beyond already-loaded partners).
            this.searchPartner();
        }
    },
});
