import logging

_logger = logging.getLogger(__name__)

HOYMAY_COMPANY_ID = 1


def post_init_hook(env):
    """Seed the two default tiers for Hoymay using whatever pricelist the
    installation considers the POS default. Tiers are created idempotently:
    re-installing the module will not duplicate them."""
    company = env['res.company'].browse(HOYMAY_COMPANY_ID).exists()
    if not company:
        _logger.warning("hh_member post_init: Hoymay company id=%s not found; skipping seed",
                        HOYMAY_COMPANY_ID)
        return

    Pricelist = env['product.pricelist'].sudo()
    default_pl = Pricelist.search(
        [('name', '=', 'POS Pricelist'), ('company_id', 'in', [company.id, False])],
        limit=1,
    )
    if not default_pl:
        default_pl = Pricelist.search(
            [('company_id', 'in', [company.id, False])],
            order='id asc',
            limit=1,
        )
    if not default_pl:
        _logger.warning("hh_member post_init: no pricelist available; tiers not seeded")
        return

    Tier = env['hh.member.tier'].sudo()
    tag1 = env.ref('hh_member.tag_tier_1', raise_if_not_found=False)
    tag2 = env.ref('hh_member.tag_tier_2', raise_if_not_found=False)

    if tag1 and not Tier.search([
        ('tag_id', '=', tag1.id),
        ('company_id', '=', company.id),
    ], limit=1):
        Tier.create({
            'name': 'Tier 1',
            'min_spending': 1000.0,
            'pricelist_id': default_pl.id,
            'earn_rate': 1.0,
            'redeem_value': 1.0,
            'tag_id': tag1.id,
            'company_id': company.id,
        })

    if tag2 and not Tier.search([
        ('tag_id', '=', tag2.id),
        ('company_id', '=', company.id),
    ], limit=1):
        Tier.create({
            'name': 'Tier 2',
            'min_spending': 3000.0,
            'pricelist_id': default_pl.id,
            'earn_rate': 1.0,
            'redeem_value': 1.0,
            'tag_id': tag2.id,
            'company_id': company.id,
        })
