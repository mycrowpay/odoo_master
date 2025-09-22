# -*- coding: utf-8 -*-
from odoo import api, fields, models


class TrakkaWallet(models.Model):
    _name = "trakka.wallet"
    _description = "Seller Wallet"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(required=True)
    partner_id = fields.Many2one("res.partner", required=True, index=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda s: s.env.company,
        index=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="company_id.currency_id",
        store=True,
        readonly=True,
    )

    move_ids = fields.One2many("trakka.wallet.move", "wallet_id")

    # Show current balance; compute as sudo so read restrictions on moves don't break it
    balance = fields.Monetary(
        compute="_compute_balance",
        store=False,
        compute_sudo=True,
    )

    _sql_constraints = [
        (
            "uniq_wallet_partner_company",
            "unique(partner_id, company_id)",
            "A wallet already exists for this partner in this company.",
        ),
    ]

    @api.depends("move_ids.amount", "move_ids.direction")
    def _compute_balance(self):
        for w in self:
            bal = 0.0
            for m in w.move_ids:
                bal += m.amount if m.direction == "in" else -m.amount
            w.balance = bal

    @api.model
    def _ensure_partner_wallet(self, partner):
        """Return the wallet for (partner, current company); create with sudo if missing."""
        company = self.env.company
        wallet = self.sudo().search(
            [("partner_id", "=", partner.id), ("company_id", "=", company.id)],
            limit=1,
        )
        if not wallet:
            wallet = self.sudo().create({
                "name": f"Wallet {partner.display_name}",
                "partner_id": partner.id,
                "company_id": company.id,
            })
        return wallet


class TrakkaWalletMove(models.Model):
    _name = "trakka.wallet.move"
    _description = "Wallet Movement"
    _order = "id desc"

    wallet_id = fields.Many2one("trakka.wallet", required=True, ondelete="cascade", index=True)

    # Keep these consistent with the wallet via related fields
    partner_id = fields.Many2one(
        "res.partner",
        related="wallet_id.partner_id",
        store=True,
        readonly=True,
        index=True,
    )
    company_id = fields.Many2one(
        "res.company",
        related="wallet_id.company_id",
        store=True,
        readonly=True,
        index=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="wallet_id.company_id.currency_id",
        store=True,
        readonly=True,
    )

    amount = fields.Monetary(required=True)
    direction = fields.Selection([("in", "Credit"), ("out", "Debit")], required=True)
    ref = fields.Char()
    date = fields.Datetime(default=fields.Datetime.now)
