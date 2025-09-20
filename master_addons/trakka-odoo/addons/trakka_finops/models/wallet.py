# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class TrakkaWallet(models.Model):
    _name = "trakka.wallet"
    _description = "Trakka Seller Wallet"
    _order = "id desc"
    _check_company_auto = True

    name = fields.Char(required=True, default="Wallet")

    partner_id = fields.Many2one(
        "res.partner",
        required=True,
        index=True,
    )

    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )

    currency_id = fields.Many2one(
        "res.currency",
        required=True,
        default=lambda self: self.env.company.currency_id,  # record, not .id
    )

    move_ids = fields.One2many("trakka.wallet.move", "wallet_id")

    balance = fields.Monetary(
        currency_field="currency_id",
        compute="_compute_balance",
        store=False,
        readonly=True,
    )

    _sql_constraints = [
        ("uniq_partner_currency_company",
         "unique(partner_id, currency_id, company_id)",
         "One wallet per partner, currency, and company."),
    ]

    @api.depends("move_ids.amount", "move_ids.move_type")
    def _compute_balance(self):
        for w in self:
            total = 0.0
            for m in w.move_ids:
                total += m.amount if m.move_type == "in" else -m.amount
            w.balance = total

    # utility
    def _get_or_create_wallet(self, partner, currency):
        """Return wallet for (partner, currency, company). Create if missing."""
        Currency = self.env["res.currency"]
        if isinstance(currency, int):
            currency = Currency.browse(currency)
        if not currency:
            currency = self.env.company.currency_id

        Wallet = self.env["trakka.wallet"].sudo()
        w = Wallet.search([
            ("partner_id", "=", partner.id),
            ("currency_id", "=", currency.id),
            ("company_id", "=", self.env.company.id),
        ], limit=1)
        if w:
            return w
        return Wallet.create({
            "name": f"Wallet {partner.display_name}",
            "partner_id": partner.id,
            "currency_id": currency.id,
            "company_id": self.env.company.id,
        })


class TrakkaWalletMove(models.Model):
    _name = "trakka.wallet.move"
    _description = "Trakka Wallet Move"
    _order = "id desc"
    _check_company_auto = True

    wallet_id = fields.Many2one(
        "trakka.wallet",
        required=True,
        ondelete="cascade",
        check_company=True,
    )

    # Matches the view (tree/form uses move_type)
    move_type = fields.Selection(
        [("in", "In"), ("out", "Out")],
        required=True,
        default="in",
        index=True,
    )

    # >>> Added to match your views <<<
    name = fields.Char(default="Move")
    date = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    related_move_id = fields.Many2one(
        "account.move",
        string="Related Journal Entry",
        index=True,
        check_company=True,
    )

    amount = fields.Monetary(currency_field="currency_id", required=True)

    currency_id = fields.Many2one(
        related="wallet_id.currency_id",
        store=True,
        readonly=True,
    )

    company_id = fields.Many2one(
        "res.company",
        related="wallet_id.company_id",
        store=True,
        readonly=True,
        index=True,
    )

    ref = fields.Char()
    idempotency_key = fields.Char(index=True)

    _sql_constraints = [
        ("amount_positive", "CHECK(amount >= 0)", "Amount must be positive."),
        ("unique_idem", "unique(idempotency_key)", "Duplicate idempotency key."),
    ]

    @api.constrains("idempotency_key")
    def _check_idem(self):
        for rec in self:
            if rec.idempotency_key and rec.search_count([
                ("id", "!=", rec.id), ("idempotency_key", "=", rec.idempotency_key)
            ]):
                raise ValidationError(_("Duplicate idempotency key."))
