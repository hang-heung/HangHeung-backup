from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """Remove the orphan loyalty artifacts the old coupon-based approach
    created: backing coupon programs, their issued cards, and the gift
    product tags. The new flow applies the free gift directly in POS."""
    env = api.Environment(cr, SUPERUSER_ID, {})

    programs = env['loyalty.program'].sudo().search([
        ('name', 'like', '[會員買X送一]%'),
    ])
    if programs:
        cards = env['loyalty.card'].sudo().search([
            ('program_id', 'in', programs.ids),
        ])
        if cards:
            cards.unlink()
        # A program can't be deleted while active — archive first.
        programs.write({'active': False})
        programs.unlink()

    tags = env['product.tag'].sudo().search([
        ('name', 'like', '[會員贈品]%'),
    ])
    if tags:
        tags.unlink()
