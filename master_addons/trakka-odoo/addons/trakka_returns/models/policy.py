# -*- coding: utf-8 -*-
from odoo import fields, models

class TrakkaReturnPolicy(models.Model):
    _name = "trakka.policy"
    _description = "Trakka Return Policy"

    name = fields.Char(required=True)
    code = fields.Selection([
        ("standard", "Standard"),
        ("friendly", "Friendly"),
        ("strict", "Strict"),
    ], required=True)
    handling_fee_min = fields.Monetary()
    handling_fee_max = fields.Monetary()
    currency_id = fields.Many2one(
        "res.currency", default=lambda s: s.env.company.currency_id.id
    )
