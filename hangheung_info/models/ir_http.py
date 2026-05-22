# -*- coding: utf-8 -*-

from odoo import models
from datetime import datetime, timedelta


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    def session_info(self):
        result = super(IrHttp, self).session_info()
        result['warning'] = False
        result['expiration_date'] = (datetime.today() + timedelta(days=2)).strftime("%Y-%m-%d")
        result['expiration_reason'] = False
        return result
