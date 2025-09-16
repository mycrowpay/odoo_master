# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

class TrakkaWallet(models.Model):
    _name = "trakka.wallet"
    _description = "Seller Wallet (Liability sub-ledger)"
    _order = "id desc"

    name = fields.Char(required=True)
    partner_id = fields.Many2one("res.partner", required=True, index=True)
    currency_id = fields.Many2one(
        "res.currency", default=lambda s: s.env.company.currency_id.id, required=True
    )
    balance = fields.Monetary(currency_field="currency_id", readonly=True, default=0)
    move_ids = fields.One2many("trakka.wallet.move", "wallet_id", string="Moves", readonly=True)

    _sql_constraints = [
        ("uniq_partner_currency", "unique(partner_id,currency_id)",
         "One wallet per partner & currency."),
    ]

    @api.model
    def _get_or_create_wallet(self, partner, currency):
        wallet = self.search([
            ("partner_id", "=", partner.id),
            ("currency_id", "=", currency.id),
        ], limit=1)
        if wallet:
            return wallet
        return self.create({
            "name": f"Wallet - {partner.display_name}",
            "partner_id": partner.id,
            "currency_id": currency.id,
        })


class TrakkaWalletMove(models.Model):
    _name = "trakka.wallet.move"
    _description = "Wallet Movement"
    _order = "id desc"

    wallet_id = fields.Many2one("trakka.wallet", required=True, ondelete="cascade")
    amount = fields.Monetary(currency_field="currency_id", required=True)
    currency_id = fields.Many2one("res.currency", related="wallet_id.currency_id", store=True)
    direction = fields.Selection([("in", "In"), ("out", "Out")], required=True)
    ref = fields.Char()
    idempotency_key = fields.Char(index=True)

    _sql_constraints = [
        ("uniq_idem", "unique(idempotency_key)", "Duplicate money op (idempotency)."),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        moves = super().create(vals_list)
        # Update wallet balances (atomic per move)
        for m in moves:
            sign = 1 if m.direction == "in" else -1
            m.wallet_id.balance = (m.wallet_id.balance or 0) + sign * m.amount
            if m.wallet_id.balance < 0:
                raise ValidationError(_("Wallet balance cannot go negative."))
        return moves
