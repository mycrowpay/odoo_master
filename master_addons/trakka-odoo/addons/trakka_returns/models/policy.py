# -*- coding: utf-8 -*-
from odoo import api, fields, models

class TrakkaPolicy(models.Model):
    _name = "trakka.policy"
    _description = "Trakka Return Policy"
    _order = "sequence, name"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one("res.company", default=lambda s: s.env.company, index=True, required=True)
    active = fields.Boolean(default=True)

    # Base fee: charged to buyer, deducted from refund (simple model)
    fee_type = fields.Selection([("fixed", "Fixed"), ("percent", "Percent")], default="fixed", required=True)
    fee_value = fields.Monetary(string="Fee Value", required=True, default=0.0)
    currency_id = fields.Many2one("res.currency", default=lambda s: s.env.company.currency_id, required=True)

    allow_overrides = fields.Boolean(default=False, help="Allow manual override on the case.")
    notes = fields.Text()

    override_ids = fields.One2many("trakka.policy.override", "policy_id", string="Category Overrides")


class TrakkaPolicyOverride(models.Model):
    _name = "trakka.policy.override"
    _description = "Trakka Return Policy Category Override"

    policy_id = fields.Many2one("trakka.policy", required=True, ondelete="cascade")
    category_id = fields.Many2one("product.category", required=True, index=True)
    fee_type = fields.Selection([("fixed", "Fixed"), ("percent", "Percent")], required=True)
    fee_value = fields.Monetary(required=True)
    currency_id = fields.Many2one("res.currency", related="policy_id.currency_id", store=True)
    allow_overrides = fields.Boolean(help="Override allow_overrides for this category; blank = inherit", default=False)
    apply_allow_overrides = fields.Boolean(
        help="If checked, use 'allow_overrides' flag above instead of inheriting from base policy.",
        default=False
    )
