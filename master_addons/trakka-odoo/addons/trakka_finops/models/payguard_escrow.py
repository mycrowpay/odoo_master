# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class TrakkaPayguardEscrow(models.Model):
    _name = "trakka.payguard.escrow"
    _description = "Trakka PayGuard Escrow"
    _order = "id desc"

    # ---- Core fields ----
    name = fields.Char(required=True, default="ESCROW")
    sale_order_id = fields.Many2one("sale.order", required=True, index=True)
    partner_id = fields.Many2one(
        "res.partner",
        related="sale_order_id.partner_id",
        store=True,
        index=True,
    )
    amount = fields.Monetary(currency_field="currency_id", required=True)
    currency_id = fields.Many2one(
        "res.currency",
        default=lambda s: s.env.company.currency_id.id,
        required=True,
    )
    mpesa_ref = fields.Char(help="Payment reference (e.g., STK push ref)")

    state = fields.Selection(
        [
            ("held", "Held"),
            ("released_ready", "Release Ready"),
            ("released", "Released"),
            ("refunded_partial", "Refunded (Partial)"),
            ("refunded_full", "Refunded (Full)"),
        ],
        default="held",
        index=True,
    )

    # UI helper (for header button visibility in v17)
    can_mark_released_ready = fields.Boolean(
        compute="_compute_ui_flags", store=False
    )

    # Idempotency for hold (created by API)
    idempotency_key = fields.Char(index=True, help="Ensure idempotent money ops")

    # Settlement artifacts
    settlement_move_id = fields.Many2one("account.move", readonly=True)
    wallet_move_id = fields.Many2one("trakka.wallet.move", readonly=True)
    settlement_batch_id = fields.Many2one("trakka.settlement.batch", readonly=True)

    _sql_constraints = [
        ("escrow_amount_positive", "CHECK(amount >= 0)", "Escrow amount must be positive."),
    ]

    # ---- UI flags ----
    @api.depends("state")
    def _compute_ui_flags(self):
        for rec in self:
            rec.can_mark_released_ready = rec.state == "held"

    # ---- Actions ----
    def action_mark_released_ready(self):
        for rec in self:
            if rec.state != "held":
                raise ValidationError(_("Only 'held' escrows can move to 'released_ready'."))
            rec.state = "released_ready"
        return True

    # ---- Helpers for posting ----
    def _get_accounts(self):
        """Resolve liability journals/accounts (created by XML data)."""
        company = self.env.company
        J = self.env["account.journal"].sudo()

        esc_journal = J.search([("code", "=", "ESC"), ("company_id", "=", company.id)], limit=1)
        wlt_journal = J.search([("code", "=", "WLT"), ("company_id", "=", company.id)], limit=1)

        if (
            not esc_journal
            or not wlt_journal
            or not esc_journal.default_account_id
            or not wlt_journal.default_account_id
        ):
            raise UserError(
                _(
                    "FinOps journals/accounts are not configured. "
                    "Ensure 'Escrow Liability' (ESC) and 'Seller Wallet' (WLT) journals have default accounts."
                )
            )

        return {
            "escrow_journal": esc_journal,
            "wallet_journal": wlt_journal,
            "escrow_account": esc_journal.default_account_id,
            "wallet_account": wlt_journal.default_account_id,
        }

    def _post_settlement_move(self, batch):
        """Post Dr Escrow Liability / Cr Seller Wallet and update wallet."""
        self.ensure_one()
        if self.state != "released_ready":
            raise ValidationError(_("Escrow must be 'released_ready' to settle."))

        acc = self._get_accounts()
        partner = self.partner_id.commercial_partner_id
        amount = self.amount

        # 1) Create & post accounting move
        move_vals = {
            "ref": f"Settle {self.name} ({self.id})",
            "journal_id": acc["escrow_journal"].id,
            "line_ids": [
                (0, 0, {
                    "name": f"Release escrow {self.name}",
                    "partner_id": partner.id,
                    "account_id": acc["escrow_account"].id,
                    "debit": amount,
                    "credit": 0.0,
                    "currency_id": self.currency_id.id if self.currency_id != self.env.company.currency_id else False,
                    "amount_currency": amount if self.currency_id != self.env.company.currency_id else 0.0,
                }),
                (0, 0, {
                    "name": f"Credit seller wallet {partner.display_name}",
                    "partner_id": partner.id,
                    "account_id": acc["wallet_account"].id,
                    "debit": 0.0,
                    "credit": amount,
                    "currency_id": self.currency_id.id if self.currency_id != self.env.company.currency_id else False,
                    "amount_currency": -amount if self.currency_id != self.env.company.currency_id else 0.0,
                }),
            ],
        }
        move = self.env["account.move"].sudo().create(move_vals)
        move.action_post()

        # 2) Wallet credit (idempotent on escrow id)
        wallet = self.env["trakka.wallet"].sudo()._get_or_create_wallet(partner, self.currency_id)
        w_move = self.env["trakka.wallet.move"].sudo().create({
            "wallet_id": wallet.id,
            "amount": amount,
            "direction": "in",
            "ref": f"settle:{self.id}",
            "idempotency_key": f"settle:escrow:{self.id}",
        })

        # 3) Update escrow
        self.write({
            "state": "released",
            "settlement_move_id": move.id,
            "wallet_move_id": w_move.id,
            "settlement_batch_id": batch.id if batch else False,
        })
        return move
