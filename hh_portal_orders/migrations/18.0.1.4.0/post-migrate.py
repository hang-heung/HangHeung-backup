# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Backfill the new portal.order.control.flow_type from company_id.

    The new required field is created with default 'consignee', so every
    existing row is already 'consignee'. Correct the HangHeung (company 3)
    records to 'customer' so behaviour is unchanged after upgrade:
        company_id = 3  -> 'customer'  (direct HangHeung sale order)
        everything else -> 'consignee' (Hoymay PO intercompany chain)
    """
    cr.execute("""
        UPDATE portal_order_control
        SET flow_type = 'customer'
        WHERE company_id = 3
          AND (flow_type IS NULL OR flow_type = 'consignee')
    """)
    _logger.info("hh_portal_orders: flow_type backfilled, %s rows set to 'customer'", cr.rowcount)
