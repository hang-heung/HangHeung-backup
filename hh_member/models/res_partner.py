from datetime import date, datetime

from dateutil.relativedelta import relativedelta

from odoo import models, fields, api


HOYMAY_COMPANY_ID = 1


class ResPartner(models.Model):
    _inherit = 'res.partner'

    member_tier_id = fields.Many2one(
        'hh.member.tier',
        string='會員等級',
        compute='_compute_member_tier_id',
        store=True,
        readonly=True,
    )
    subscription_date = fields.Date(
        string='成為會員日期',
        readonly=True,
    )
    hh_free_progress_ids = fields.One2many(
        'hh.member.free.progress',
        'partner_id',
        string='買X送一進度',
    )

    # ------------------------------------------------------------------
    # Auto-enrol new individual customers when a zero-threshold tier exists
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        # If a registration tier (min_spending <= 0) is configured, a newly
        # registered individual customer should immediately become a member.
        has_zero_tier = self.env['hh.member.tier'].sudo().search_count([
            ('company_id', '=', HOYMAY_COMPANY_ID),
            ('min_spending', '<=', 0),
        ])
        if has_zero_tier:
            for partner in partners:
                if partner.partner_share and not partner.is_company:
                    partner._evaluate_tier()
        return partners

    # ------------------------------------------------------------------
    # Compute: member_tier_id derived from the partner's category_id tags
    # ------------------------------------------------------------------
    @api.depends('category_id')
    def _compute_member_tier_id(self):
        Tier = self.env['hh.member.tier'].sudo()
        all_tiers = Tier.search([])
        tag_to_tier = {t.tag_id.id: t for t in all_tiers if t.tag_id}
        for rec in self:
            hit_tiers = [tag_to_tier[c.id] for c in rec.category_id if c.id in tag_to_tier]
            if hit_tiers:
                best = max(hit_tiers, key=lambda t: t.min_spending)
                rec.member_tier_id = best.id
            else:
                rec.member_tier_id = False

    # ------------------------------------------------------------------
    # Tier evaluation
    # ------------------------------------------------------------------
    def _get_spending_last_365_days_hoymay(self):
        """Trailing 365-day Hoymay POS spend (paid/done/invoiced, > 0)."""
        self.ensure_one()
        start_dt = datetime.combine(
            date.today() - relativedelta(days=365),
            datetime.min.time(),
        )
        orders = self.env['pos.order'].sudo().search([
            ('partner_id', '=', self.id),
            ('state', 'in', ['paid', 'done', 'invoiced']),
            ('date_order', '>=', start_dt),
            ('amount_total', '>', 0),
            ('company_id', '=', HOYMAY_COMPANY_ID),
        ])
        return sum(orders.mapped('amount_total'))

    def _target_tier(self):
        """Highest active tier whose min_spending threshold the partner meets."""
        self.ensure_one()
        spending = self._get_spending_last_365_days_hoymay()
        Tier = self.env['hh.member.tier'].sudo()
        for tier in Tier.search(
            [('company_id', '=', HOYMAY_COMPANY_ID)],
            order='min_spending desc',
        ):
            if spending >= tier.min_spending:
                return tier
        return Tier.browse()

    def _current_tier(self):
        """The tier currently stamped on this partner (via category tag)."""
        return self.sudo().member_tier_id

    def _all_tier_tags(self):
        return self.env['hh.member.tier'].sudo().search([]).mapped('tag_id')

    def _apply_tier(self, tier):
        """Stamp the tier's tag, drop any other tier tags, apply pricelist,
        and refresh subscription_date. All operations done with sudo so
        the cron / paid-order hook can run as the cashier user."""
        self.ensure_one()
        partner = self.sudo()
        other_tier_tags = self._all_tier_tags() - tier.tag_id
        cat_cmds = [(3, t.id) for t in (partner.category_id & other_tier_tags)]
        if tier.tag_id and tier.tag_id.id not in partner.category_id.ids:
            cat_cmds.append((4, tier.tag_id.id))
        vals = {'subscription_date': date.today()}
        if cat_cmds:
            vals['category_id'] = cat_cmds
        partner.write(vals)
        if tier.pricelist_id:
            partner.property_product_pricelist = tier.pricelist_id

    def _remove_tier(self):
        """Drop all tier tags and clear subscription_date. Leave pricelist
        falling back to system default."""
        self.ensure_one()
        partner = self.sudo()
        all_tags = self._all_tier_tags()
        cat_cmds = [(3, t.id) for t in (partner.category_id & all_tags)]
        vals = {'subscription_date': False}
        if cat_cmds:
            vals['category_id'] = cat_cmds
        partner.write(vals)
        # Clear partner-level pricelist override so the property falls
        # back to whatever the system default is.
        partner.property_product_pricelist = False

    def _renew_tier(self, tier):
        """Reset subscription_date to today; keep the same tier."""
        self.ensure_one()
        partner = self.sudo()
        partner.write({'subscription_date': date.today()})
        if tier.pricelist_id:
            partner.property_product_pricelist = tier.pricelist_id

    def _evaluate_tier(self):
        """Apply the correct tier to a single partner based on spending,
        the 365-day hold, and mid-cycle upgrade rule.

        Internal partners (partner_share=False — employees, users, the 18
        shop contact records) are never tiered. If one happens to carry a
        legacy tier tag, strip it here."""
        self.ensure_one()
        if not self.partner_share:
            if self._current_tier():
                self._remove_tier()
            return

        today = date.today()
        target = self._target_tier()
        current = self._current_tier()

        if not current:
            if target:
                self._apply_tier(target)
            return

        days_held = (today - self.subscription_date).days if self.subscription_date else 999
        if days_held >= 365:
            # Hold expired: renew, switch, or drop
            if target and target.id == current.id:
                self._renew_tier(current)
            elif target:
                self._apply_tier(target)
            else:
                self._remove_tier()
        else:
            # Mid-cycle: upgrade only, never downgrade
            if target and target.min_spending > current.min_spending:
                self._apply_tier(target)

    # ------------------------------------------------------------------
    # Cron entry point
    # ------------------------------------------------------------------
    def action_check_membership_tiers(self):
        """Sweep partners that either spent on Hoymay POS in the last 365
        days, or currently carry a tier tag, and re-evaluate each.

        Spending source is filtered to external partners (partner_share=True)
        only. Tier-tag holders are included unconditionally so any internal
        partner that picked up a tag is cleaned up by _evaluate_tier."""
        start_dt = datetime.combine(
            date.today() - relativedelta(days=365),
            datetime.min.time(),
        )

        partner_ids = set(
            self.env['pos.order'].sudo().search([
                ('state', 'in', ['paid', 'done', 'invoiced']),
                ('date_order', '>=', start_dt),
                ('amount_total', '>', 0),
                ('partner_id', '!=', False),
                ('partner_id.partner_share', '=', True),
                ('company_id', '=', HOYMAY_COMPANY_ID),
            ]).mapped('partner_id.id')
        )

        all_tags = self._all_tier_tags()
        if all_tags:
            partner_ids |= set(
                self.sudo().search([('category_id', 'in', all_tags.ids)]).ids
            )

        for partner in self.browse(list(partner_ids)):
            partner._evaluate_tier()
