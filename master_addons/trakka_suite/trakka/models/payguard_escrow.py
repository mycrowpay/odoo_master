# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class TrakkaPayguardEscrow(models.Model):
    _name = "trakka.payguard.escrow"
    _description = "PayGuard Escrow"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    # Human-meaningful sequence (ESC/%(year)s/%(month)s/%(seq))
    name = fields.Char(
        default=lambda self: self.env["ir.sequence"].next_by_code("trakka.payguard.escrow"),
        readonly=True,
        copy=False,
        tracking=True,
    )

    # IMPORTANT: real field with default so check_company on sale_order_id can work immediately
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
        tracking=True,
    )

    # Filters by company_id automatically thanks to check_company=True
    sale_order_id = fields.Many2one(
        "sale.order",
        required=True,
        check_company=True,
        index=True,
        tracking=True,
    )

    # Related helpers from SO
    currency_id = fields.Many2one(
        "res.currency",
        related="sale_order_id.currency_id",
        store=True,
        readonly=True,
    )
    partner_id = fields.Many2one(
        "res.partner",
        related="sale_order_id.partner_id",
        store=True,
        readonly=True,
    )

    amount = fields.Monetary(required=True, tracking=True)
    state = fields.Selection(
        [
            ("held", "Held"),
            ("released_ready", "Release Ready"),
            ("released", "Released"),
        ],
        default="held",
        tracking=True,
        index=True,
    )

    idempotency_key = fields.Char(index=True)
    account_move_id = fields.Many2one("account.move", readonly=True)
    wallet_move_id = fields.Many2one("trakka.wallet.move", readonly=True)

    # -----------------------
    # Onchanges / helpers
    # -----------------------
    @api.onchange("sale_order_id")
    def _onchange_sale_order_id(self):
        """Prefill amount and snap company to the SO's company."""
        if self.sale_order_id:
            self.company_id = self.sale_order_id.company_id
            self.amount = self.sale_order_id.amount_total or 0.0

    def action_set_release_ready(self):
        for rec in self:
            rec.state = "released_ready"

    def _get_required_journals(self):
        """Return (ESC, WLT) journals for this record's company."""
        company = self.company_id
        esc = self.env["account.journal"].with_company(company).search([("code", "=", "ESC")], limit=1)
        wlt = self.env["account.journal"].with_company(company).search([("code", "=", "WLT")], limit=1)
        return esc, wlt

    # -----------------------
    # Settlement
    # -----------------------
    def action_post_settlement_move(self):
        """Dr ESC liability / Cr WLT liability, then credit Wallet and mark released."""
        self.ensure_one()

        if self.state != "released_ready":
            raise ValidationError(_("Escrow must be Release Ready before settlement."))

        partner = self.sale_order_id.partner_id

        # Phone validation (to avoid downstream SMS errors in your flows)
        if not (partner.mobile or partner.phone) and not self.env.context.get("trakka_skip_sms"):
            raise ValidationError(
                _("Customer phone/mobile is required to post settlement. "
                  "Please add it on the Sales Order customer.")
            )

        esc_journal, wlt_journal = self._get_required_journals()
        if not esc_journal or not wlt_journal:
            raise ValidationError(_("Missing ESC/WLT journals for company %s.") % self.company_id.display_name)
        if not esc_journal.default_account_id or not wlt_journal.default_account_id:
            raise ValidationError(_("Please configure default accounts on ESC and WLT journals."))

        if not self.amount or self.amount <= 0.0:
            raise ValidationError(_("Escrow amount must be greater than zero."))

        company = self.company_id

        # Single JE posted in the ESC journal; lines use ESC & WLT default accounts
        move_vals = {
            "journal_id": esc_journal.id,
            "date": fields.Date.context_today(self),
            "ref": self.name,
            "line_ids": [
                # Dr ESC Liability
                (0, 0, {
                    "name": _("Escrow Release %s") % self.name,
                    "account_id": esc_journal.default_account_id.id,
                    "debit": self.amount,
                    "credit": 0.0,
                    "partner_id": partner.id,
                    "company_id": company.id,
                }),
                # Cr WLT Liability
                (0, 0, {
                    "name": _("Wallet Credit %s") % self.name,
                    "account_id": wlt_journal.default_account_id.id,
                    "debit": 0.0,
                    "credit": self.amount,
                    "partner_id": partner.id,
                    "company_id": company.id,
                }),
            ],
            "company_id": company.id,
        }

        move = self.env["account.move"].with_company(company).create(move_vals)
        move.with_company(company).action_post()

        # Credit seller wallet
        wallet = self.env["trakka.wallet"].with_company(company)._ensure_partner_wallet(partner)
        wmove = self.env["trakka.wallet.move"].with_company(company).create({
            "wallet_id": wallet.id,
            "partner_id": partner.id,
            "amount": self.amount,
            "direction": "in",
            "ref": self.name,
            "company_id": company.id,
        })

        self.write({
            "state": "released",
            "account_move_id": move.id,
            "wallet_move_id": wmove.id,
        })
        self.message_post(body=_("Settlement posted. JE %s; Wallet credited.") % (move.name or move.id))
        return True
