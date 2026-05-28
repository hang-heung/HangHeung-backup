def migrate(cr, version):
    """Carry the legacy single free_product_id into the new free_product_ids
    M2M. The old column lingers after the field was removed from the model, so
    we read it directly and seed the relation table."""
    cr.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'hh_member_free_rule' AND column_name = 'free_product_id'
    """)
    if not cr.fetchone():
        return
    cr.execute("""
        INSERT INTO hh_member_free_rule_freeprod_rel (rule_id, product_id)
        SELECT id, free_product_id FROM hh_member_free_rule
        WHERE free_product_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """)
