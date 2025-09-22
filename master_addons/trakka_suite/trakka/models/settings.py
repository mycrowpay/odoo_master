# -*- coding: utf-8 -*-
from odoo import api, fields, models

# Company-level configuration (actual storage)
class ResCompany(models.Model):
    _inherit = "res.company"

    trakka_escrow_default_policy = fields.Selection(
        selection=[
            ("auto_on_delivery", "Auto on Delivery"),
            ("auto_after_cooldown", "Auto after Cooldown"),
            ("manual", "Manual"),
        ],
        string="Default Escrow Release Policy",
        default="auto_on_delivery",
        help="Default policy used for newly created escrows.",
    )

    trakka_escrow_release_cooldown_days = fields.Integer(
        string="Escrow Release Cooldown (days)",
        default=0,
        help="If > 0 and policy is 'Auto after Cooldown', wait this many days before auto-settlement.",
    )

    trakka_require_invoice_before_settlement = fields.Boolean(
        string="Require Invoice Before Settlement",
        default=False,
        help="If enabled, dispatch cannot mark Delivered unless an invoice exists "
             "(and you can enforce posted invoice in your flow if needed).",
    )


# Settings proxy (General Settings UI)
class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    trakka_escrow_default_policy = fields.Selection(
        related="company_id.trakka_escrow_default_policy",
        readonly=False,
    )
    trakka_escrow_release_cooldown_days = fields.Integer(
        related="company_id.trakka_escrow_release_cooldown_days",
        readonly=False,
    )
    trakka_require_invoice_before_settlement = fields.Boolean(
        related="company_id.trakka_require_invoice_before_settlement",
        readonly=False,
    )
