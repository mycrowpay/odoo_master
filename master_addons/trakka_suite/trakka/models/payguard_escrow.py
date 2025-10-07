# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class TrakkaPayguardEscrow(models.Model):
    _name = "trakka.payguard.escrow"
    _description = "PayGuard Escrow"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    # -------------------------------------------------
    # Identity / linkage
    # -------------------------------------------------
    name = fields.Char(
        default=lambda self: self.env["ir.sequence"].next_by_code("trakka.payguard.escrow"),
        readonly=True,
        copy=False,
        tracking=True,
    )

    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
        tracking=True,
    )

    sale_order_id = fields.Many2one(
        "sale.order",
        required=True,
        check_company=True,
        index=True,
        copy=False,
        domain=[("state", "in", ["sale", "done"])],
        tracking=True,
    )

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

    amount = fields.Monetary(required=True, tracking=True, copy=False)

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

    idempotency_key = fields.Char(index=True, copy=False)
    account_move_id = fields.Many2one("account.move", readonly=True, copy=False)
    wallet_move_id = fields.Many2one("trakka.wallet.move", readonly=True, copy=False)

    # -------------------------------------------------
    # Release policy / audit (NEW)
    # -------------------------------------------------
    release_policy = fields.Selection(
        [
            ("manual", "Manual"),
            ("auto_on_delivery", "Auto on Delivery"),
            ("auto_after_cooldown", "Auto after Cooldown"),
        ],
        default="auto_on_delivery",
        required=True,
        tracking=True,
        help="How funds should be released for this escrow.",
    )
    release_cooldown_days = fields.Integer(
        default=0,
        help="If policy is 'Auto after Cooldown', wait this many days after marking Release Ready.",
    )
    release_ready_at = fields.Datetime(readonly=True, tracking=True)
    released_at = fields.Datetime(readonly=True, tracking=True)

    allow_manual_override = fields.Boolean(
        help="Permit a FinOps manager to force Release Ready from Held."
    )
    override_reason = fields.Char()

    # -------------------------------------------------
    # Smart-button helpers (computed, not stored)
    # -------------------------------------------------
    sale_order_count = fields.Integer(
        compute="_compute_links_counts", string="Sale Order(s)"
    )
    dispatch_count = fields.Integer(
        compute="_compute_links_counts", string="Dispatch(es)"
    )
    has_sale_order = fields.Boolean(compute="_compute_links_counts")
    has_dispatch = fields.Boolean(compute="_compute_links_counts")

    latest_dispatch_id = fields.Many2one(
        "trakka.dispatch.order",
        compute="_compute_latest_dispatch_info",
        string="Latest Dispatch",
        readonly=True,
    )
    latest_dispatch_state = fields.Selection(
        [
            ("new", "New"),
            ("assigned", "Assigned"),
            ("accepted", "Accepted"),
            ("picked", "Picked"),
            ("on_route", "On Route"),
            ("delivered", "Delivered"),
            ("failed", "Failed"),
        ],
        compute="_compute_latest_dispatch_info",
        string="Dispatch Status",
        readonly=True,
    )

    _sql_constraints = [
        ("uniq_escrow_so", "unique(sale_order_id)", "An escrow already exists for this Sales Order."),
        ("uniq_escrow_idempotency", "unique(idempotency_key)", "Duplicate idempotency key."),
    ]

    # -------------------------------------------------
    # Lifecycle guards
    # -------------------------------------------------
    @api.model
    def create(self, vals):
        so_id = vals.get("sale_order_id")
        if so_id:
            so = self.env["sale.order"].browse(so_id)
            vals.setdefault("company_id", so.company_id.id)
            vals.setdefault("amount", so.amount_total or 0.0)

        if not vals.get("amount") or vals["amount"] <= 0.0:
            raise ValidationError(_("Escrow amount must be greater than zero."))

        rec = super().create(vals)
        rec._ensure_idempotency_key()
        return rec

    def write(self, vals):
        if "sale_order_id" in vals:
            raise ValidationError(_("You cannot change the Sales Order of an existing Escrow."))

        if "amount" in vals and any(r.state != "held" for r in self):
            raise ValidationError(_("You can only change the amount while Escrow is in Held."))

        return super().write(vals)

    def unlink(self):
        for rec in self:
            if rec.state != "held":
                raise ValidationError(_("You can only delete Escrows in Held state."))
            if rec.account_move_id or rec.wallet_move_id:
                raise ValidationError(_("You cannot delete an Escrow that has posted accounting or wallet moves."))
        return super().unlink()

    # -------------------------------------------------
    # Helpers / onchange / computes
    # -------------------------------------------------
    def _ensure_idempotency_key(self):
        for rec in self:
            if not rec.idempotency_key:
                cents = int((rec.amount or 0.0) * 100)
                rec.idempotency_key = f"escrow:{rec.id}:release:{cents}"

    @api.onchange("sale_order_id")
    def _onchange_sale_order_id(self):
        if self.sale_order_id:
            self.company_id = self.sale_order_id.company_id
            self.amount = self.sale_order_id.amount_total or 0.0

    @api.depends("sale_order_id")
    def _compute_links_counts(self):
        Dispatch = self.env["trakka.dispatch.order"].sudo()
        for rec in self:
            so = rec.sale_order_id
            if so:
                rec.sale_order_count = 1
                rec.has_sale_order = True
                rec.dispatch_count = Dispatch.search_count([("sale_order_id", "=", so.id)])
                rec.has_dispatch = rec.dispatch_count > 0
            else:
                rec.sale_order_count = 0
                rec.has_sale_order = False
                rec.dispatch_count = 0
                rec.has_dispatch = False

    @api.depends("sale_order_id")
    def _compute_latest_dispatch_info(self):
        Dispatch = self.env["trakka.dispatch.order"].sudo()
        for rec in self:
            rec.latest_dispatch_id = False
            rec.latest_dispatch_state = False
            if rec.sale_order_id:
                last = Dispatch.search(
                    [("sale_order_id", "=", rec.sale_order_id.id)],
                    order="id desc",
                    limit=1,
                )
                rec.latest_dispatch_id = last.id if last else False
                rec.latest_dispatch_state = last.state if last else False

    # -------------------------------------------------
    # State transitions
    # -------------------------------------------------
    def action_set_release_ready(self):
        for rec in self:
            if rec.state != "held":
                raise ValidationError(_("Only Held escrows can be marked Release Ready."))
            if not rec.amount or rec.amount <= 0.0:
                raise ValidationError(_("Escrow amount must be greater than zero."))

            rec.write({
                "state": "released_ready",
                "release_ready_at": fields.Datetime.now(),
            })

            # Optional inline auto-release behaviors
            if rec.release_policy == "auto_on_delivery":
                if rec.latest_dispatch_state == "delivered":
                    rec.action_post_settlement_move()
            # For 'auto_after_cooldown', cron will handle it later.

    def _get_required_journals(self):
        """Return (ESC, WLT) journals for this record's company."""
        company = self.company_id
        esc = self.env["account.journal"].with_company(company).search([("code", "=", "ESC")], limit=1)
        wlt = self.env["account.journal"].with_company(company).search([("code", "=", "WLT")], limit=1)
        return esc, wlt

    # -------------------------------------------------
    # Settlement (idempotent)
    # -------------------------------------------------
    def action_post_settlement_move(self):
        self.ensure_one()

        if self.state == "released":
            return True
        
        # Enforce company toggle: must be fully invoiced first
        if self.company_id.trakka_require_invoice_before_settlement:
            if self.sale_order_id.invoice_status != "invoiced":
                raise ValidationError(
                    _("This escrow cannot be settled until the Sales Order is fully invoiced.")
                )

        if self.state != "released_ready":
            raise ValidationError(_("Escrow must be Release Ready before settlement."))

        partner = self.sale_order_id.partner_id
        if not (partner.mobile or partner.phone) and not self.env.context.get("trakka_skip_sms"):
            raise ValidationError(
                _("Customer phone/mobile is required to post settlement. "
                  "Please add it on the Sales Order customer.")
            )

        if not self.amount or self.amount <= 0.0:
            raise ValidationError(_("Escrow amount must be greater than zero."))

        esc_journal, wlt_journal = self._get_required_journals()
        if not esc_journal or not wlt_journal:
            raise ValidationError(_("Missing ESC/WLT journals for company %s.") % self.company_id.display_name)
        if not esc_journal.default_account_id or not wlt_journal.default_account_id:
            raise ValidationError(_("Please configure default accounts on ESC and WLT journals."))

        company = self.company_id
        move_vals = {
            "journal_id": esc_journal.id,
            "date": fields.Date.context_today(self),
            "ref": self.name,
            "line_ids": [
                (0, 0, {
                    "name": _("Escrow Release %s") % self.name,
                    "account_id": esc_journal.default_account_id.id,
                    "debit": self.amount,
                    "credit": 0.0,
                    "partner_id": partner.id,
                    "company_id": company.id,
                }),
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
        move = self.env["account.move"].with_company(company).sudo().create(move_vals)
        move.sudo().with_company(company).action_post()

        wallet = self.env["trakka.wallet"].with_company(company)._ensure_partner_wallet(partner)
        wmove = self.env["trakka.wallet.move"].with_company(company).sudo().create({
            "wallet_id": wallet.id,
            "amount": self.amount,
            "direction": "in",
            "ref": self.name,
        })

        self.write({
            "state": "released",
            "account_move_id": move.id,
            "wallet_move_id": wmove.id,
            "released_at": fields.Datetime.now(),
        })
        self.message_post(body=_("Settlement posted. JE %s; Wallet credited.") % (move.name or move.id))
        return True
    
    fund_state = fields.Selection(
    [("pending","Pending"),("funded","Funded"),("failed","Failed")],
    default="pending", index=True, tracking=True
)

    # -------------------------------------------------
    # Automated paths
    # -------------------------------------------------
    def _try_mark_release_ready(self, trigger="manual"):
        """Idempotently move Held -> Release Ready when policy & checks allow."""
        for rec in self.filtered(lambda r: r.state == "held"):
            if rec.release_policy == "manual" and trigger != "manual":
                continue
            if rec.sale_order_id.state in ("cancel", "draft"):
                continue
            if rec.latest_dispatch_state == "failed" and not rec.allow_manual_override:
                continue
            rec.action_set_release_ready()

    def action_override_mark_release_ready(self):
        """FinOps override path from Held → Release Ready (with audit)."""
        for rec in self:
            if rec.state != "held":
                raise ValidationError(_("Escrow is not in Held."))
            if not rec.override_reason:
                raise ValidationError(_("Provide an override reason first."))
            rec.allow_manual_override = True
            rec.message_post(body=_("FinOps override to Release Ready. Reason: %s") % rec.override_reason)
            rec.action_set_release_ready()

    @api.model
    def cron_auto_settle_ready_escrows(self):
        """Cron: settle Release Ready escrows if cooldown elapsed (for auto_after_cooldown)."""
        now = fields.Datetime.now()
        ready = self.search([("state", "=", "released_ready")])
        for rec in ready:
            # If policy isn't cooldown-based, skip (manual & delivered are handled elsewhere)
            if rec.release_policy != "auto_after_cooldown":
                continue
            if not rec.release_ready_at:
                continue
            if rec.release_cooldown_days and rec.release_cooldown_days > 0:
                delta = now - rec.release_ready_at
                if delta.days < rec.release_cooldown_days:
                    continue
            # Try settling; don't crash the cron
            try:
                rec.with_context(trakka_skip_sms=True).action_post_settlement_move()
            except Exception as e:
                rec.message_post(body=_("Auto-settle failed: %s") % e)

    # -------------------------------------------------
    # Smart-button actions
    # -------------------------------------------------
    def action_view_sale_order(self):
        """Open the linked Sales Order."""
        self.ensure_one()
        if not self.sale_order_id:
            raise UserError(_("No Sales Order is linked to this Escrow."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Sales Order"),
            "res_model": "sale.order",
            "view_mode": "form",
            "target": "current",
            "res_id": self.sale_order_id.id,
            "context": {},
        }

    def action_view_dispatches(self):
        """Open Dispatch Orders for this escrow's Sales Order."""
        self.ensure_one()
        if not self.sale_order_id:
            raise UserError(_("Link a Sales Order first to see its dispatches."))
        domain = [("sale_order_id", "=", self.sale_order_id.id)]
        action = {
            "type": "ir.actions.act_window",
            "name": _("Dispatches"),
            "res_model": "trakka.dispatch.order",
            "view_mode": "tree,form",
            "target": "current",
            "domain": domain,
            "context": {"default_sale_order_id": self.sale_order_id.id},
        }
        # If exactly one dispatch, open it directly
        dispatches = self.env["trakka.dispatch.order"].sudo().search(domain, limit=2)
        if len(dispatches) == 1:
            action["res_id"] = dispatches.id
            action["view_mode"] = "form,tree"
        return action
