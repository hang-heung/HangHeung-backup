def migrate(cr, version):
    """Drop the now-unused coupon-machinery columns from hh_member_free_rule."""
    for col in ('loyalty_program_id', 'gift_tag_id'):
        cr.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'hh_member_free_rule' AND column_name = %s",
            (col,),
        )
        if cr.fetchone():
            cr.execute("ALTER TABLE hh_member_free_rule DROP COLUMN %s" % col)
