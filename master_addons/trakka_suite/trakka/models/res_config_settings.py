# -*- coding: utf-8 -*-
from odoo import fields, models

class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    trakka_require_invoice_before_settlement = fields.Boolean(
        related="company_id.trakka_require_invoice_before_settlement",
        readonly=False
    )
