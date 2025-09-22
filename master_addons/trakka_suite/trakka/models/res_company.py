# -*- coding: utf-8 -*-
from odoo import fields, models

class ResCompany(models.Model):
    _inherit = "res.company"

    # If True: escrow settlement requires the SO to be fully invoiced (posted).
    trakka_require_invoice_before_settlement = fields.Boolean(
        string="Require Invoice before Escrow Settlement",
        default=True,
        help="When enabled, escrows cannot be settled until the related Sales Order is fully invoiced."
    )
