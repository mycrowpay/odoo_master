# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class TrakkaPayguardEscrow(models.Model):
    _name = "trakka.payguard.escrow"
    _description = "Trakka PayGuard Escrow"
    _order = "id desc"
    _check_company_auto = True  # enforce company consistency on relations

    # ---------- Name from sequence ----------
    def _default_name(self):
        """
        Requires an ir.sequence with code 'trakka.payguard.escrow'.
        Example (recommended):
          prefix = "ESC/%(year)s/%(month)s/"
          padding = 4
        """
        return self.env["ir.sequence"].next_by_code("trakka.payguard.escrow") or "ESCROW"

    # ---------- Core fields ----------
    name = fields.Char(required=True, default=_default_name, readonly=True)

    sale_order_id = fields.Many2one(
        "sale.order",
        required=True,
        index=True,
        check_company=True,  # must match escrow's company
    )

    # Company follows the SO; stored for group-by/search and shown in views
    company_id = fields.Many2one(
        "res.company",
        related="sale_order_id.company_id",
        store=True,
        readonly=True,
        index=True,
    )

    partner_id = fields.Many2one(
        "res.partner",
        related="sale_order_id.partner_id",
        store=True,
        index=True,
        readonly=True,
    )

    amount = fields.Monetary(currency_field="currency_id", required=True)

    # Currency follows the sale order (stored/readonly so it always matches SO)
    currency_id = fields.Many2one(
        "res.currency",
        related="sale_order_id.currency_id",
        store=True,
        readonly=True,
        index=True,
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
    can_mark_released_ready = fields.Boolean(compute="_compute_ui_flags", store=False)

    # Idempotency for hold (created by API)
    idempotency_key = fields.Char(index=True, help="Ensure idempotent money ops")

    # Settlement artifacts (filled by settlement actions)
    settlement_move_id = fields.Many2one("account.move", readonly=True, check_company=True)
    wallet_move_id = fields.Many2one("trakka.wallet.move", readonly=True, check_company=True)
    settlement_batch_id = fields.Many2one("trakka.settlement.batch", readonly=True, check_company=True)

    _sql_constraints = [
        ("escrow_amount_positive", "CHECK(amount >= 0)", "Escrow amount must be positive."),
    ]

    # ---------- Prefill from Sales Order ----------
    @api.onchange("sale_order_id")
    def _onchange_sale_order_id(self):
        """When the SO is picked, prefill amount from SO total."""
        if self.sale_order_id:
            self.amount = self.sale_order_id.amount_total or 0.0

    # ---------- UI flags ----------
    @api.depends("state")
    def _compute_ui_flags(self):
        for rec in self:
            rec.can_mark_released_ready = rec.state == "held"

    # ---------- Actions (UI) ----------
    def action_mark_released_ready(self):
        for rec in self:
            if rec.state != "held":
                raise ValidationError(_("Only 'held' escrows can move to 'released_ready'."))
            if rec.amount <= 0:
                raise ValidationError(_("Escrow amount must be greater than zero."))
            rec.state = "released_ready"
        return True

    def action_post_settlement_move(self):
        """Button handler from the form view. Settle each selected escrow immediately."""
        for rec in self:
            rec._post_settlement_move(batch=None)
        return True

    # ---------- Helpers ----------
    def _get_accounts(self):
        """Resolve journals/accounts for the escrow's company (not UI company)."""
        self.ensure_one()
        company = self.company_id or self.sale_order_id.company_id
        J = self.env["account.journal"].sudo().with_company(company)

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
                    "FinOps journals/accounts are not configured for %s. "
                    "Ensure 'Escrow Liability' (ESC) and 'Seller Wallet' (WLT) journals exist "
                    "and have default accounts."
                )
                % (company.display_name,)
            )

        return {
            "company": company,
            "escrow_journal": esc_journal,
            "wallet_journal": wlt_journal,
            "escrow_account": esc_journal.default_account_id,
            "wallet_account": wlt_journal.default_account_id,
        }

    def _post_settlement_move(self, batch=None):
        """Post Dr Escrow Liability / Cr Seller Wallet and update wallet."""
        self.ensure_one()
        if self.state != "released_ready":
            raise ValidationError(_("Escrow must be 'released_ready' to settle."))

        acc = self._get_accounts()
        company = acc["company"]
        partner = self.partner_id.commercial_partner_id
        amount = self.amount

        # Always post in the escrow's company
        Move = self.env["account.move"].sudo().with_company(company)

        move_vals = {
            "company_id": company.id,
            "ref": f"Settle {self.name} ({self.id})",
            "journal_id": acc["escrow_journal"].id,
            "currency_id": self.currency_id.id,  # ensure move has currency
            "line_ids": [
                (0, 0, {
                    "name": f"Release escrow {self.name}",
                    "partner_id": partner.id,
                    "account_id": acc["escrow_account"].id,
                    "debit": amount,
                    "credit": 0.0,
                    "currency_id": self.currency_id.id,
                    "amount_currency": amount,
                }),
                (0, 0, {
                    "name": f"Credit seller wallet {partner.display_name}",
                    "partner_id": partner.id,
                    "account_id": acc["wallet_account"].id,
                    "debit": 0.0,
                    "credit": amount,
                    "currency_id": self.currency_id.id,
                    "amount_currency": -amount,
                }),
            ],
        }
        move = Move.create(move_vals)

        # ---- IMPORTANT ----
        # Avoid tenant override on account.move.action_post() (SMS hook).
        # Use the low-level posting routine to bypass external side effects.
        move._post(soft=False)

        # Wallet credit (also in the escrow's company)
        Wallet = self.env["trakka.wallet"].sudo().with_company(company)
        WalletMove = self.env["trakka.wallet.move"].sudo().with_company(company)

        wallet = Wallet._get_or_create_wallet(partner, self.currency_id)
        w_move = WalletMove.create({
            "wallet_id": wallet.id,
            "amount": amount,
            "move_type": "in",
            "ref": f"settle:{self.id}",
            "idempotency_key": f"settle:escrow:{self.id}",
        })

        self.write({
            "state": "released",
            "settlement_move_id": move.id,
            "wallet_move_id": w_move.id,
            "settlement_batch_id": batch.id if batch else False,
        })
        return move
