# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.tools.safe_eval import safe_eval
from odoo.exceptions import ValidationError, UserError


class SaleOrder(models.Model):
    _inherit = "sale.order"


     # Company toggle (readable on the SO for quick checks/UI)
    trakka_require_invoice_before_settlement = fields.Boolean(
        related="company_id.trakka_require_invoice_before_settlement",
        store=False, readonly=True
    )

    # ===== Counters used by smart buttons =====
    trakka_escrow_count = fields.Integer(compute="_compute_trakka_counts", store=False)
    trakka_dispatch_count = fields.Integer(compute="_compute_trakka_counts", store=False)

    # ===== UI flags for button visibility/guards =====
    trakka_has_escrow = fields.Boolean(compute="_compute_trakka_escrow_flags", store=False)
    trakka_escrow_state = fields.Selection(
        [("held", "Held"), ("released_ready", "Release Ready"), ("released", "Released")],
        compute="_compute_trakka_escrow_flags",
        store=False,
    )


    

    # ----------------------------
    # Aggregates (smart button counters)
    # ----------------------------
    def _compute_trakka_counts(self):
        # Escrows per SO
        escrow_rg = self.env["trakka.payguard.escrow"].read_group(
            [("sale_order_id", "in", self.ids)], ["sale_order_id"], ["sale_order_id"]
        )
        esc_map = {r["sale_order_id"][0]: r["sale_order_id_count"] for r in escrow_rg}

        # Dispatches per SO (dispatch.sale_order_id is a related to picking.sale_id and is stored=True)
        dispatch_rg = self.env["trakka.dispatch.order"].read_group(
            [("sale_order_id", "in", self.ids)], ["sale_order_id"], ["sale_order_id"]
        )
        dsp_map = {r["sale_order_id"][0]: r["sale_order_id_count"] for r in dispatch_rg}

        for so in self:
            so.trakka_escrow_count = esc_map.get(so.id, 0)
            so.trakka_dispatch_count = dsp_map.get(so.id, 0)

    def _compute_trakka_escrow_flags(self):
        Escrow = self.env["trakka.payguard.escrow"].sudo()
        for so in self:
            esc = Escrow.search([("sale_order_id", "=", so.id)], limit=1)
            so.trakka_has_escrow = bool(esc)
            so.trakka_escrow_state = esc.state if esc else False

    # ----------------------------
    # Escrow actions
    # ----------------------------
    def action_trakka_create_escrow(self):
        """Create (or open) a single escrow for this SO."""
        self.ensure_one()
        Escrow = self.env["trakka.payguard.escrow"].with_company(self.company_id)

        existing = Escrow.search([("sale_order_id", "=", self.id)], limit=1)
        if existing:
            return existing.get_formview_action()

        esc = Escrow.create({
            "sale_order_id": self.id,
            "company_id": self.company_id.id,
            "amount": self.amount_total or 0.0,
        })
        return esc.get_formview_action()

    def action_trakka_view_escrows(self):
        """Smart button → open escrows filtered to this SO."""
        self.ensure_one()

        action = None
        for xmlid in ("trakka.action_trakka_escrow", "trakka.action_trakka_escrows", "trakka.action_payguard_escrows"):
            try:
                action = self.env["ir.actions.act_window"]._for_xml_id(xmlid)
                break
            except Exception:
                action = None

        if not action:
            action = {
                "type": "ir.actions.act_window",
                "name": _("Escrows"),
                "res_model": "trakka.payguard.escrow",
                "view_mode": "tree,form",
                "target": "current",
            }

        # normalize + extend context
        base_ctx = action.get("context") or {}
        if isinstance(base_ctx, str):
            base_ctx = safe_eval(base_ctx) or {}
        base_ctx.update({"default_sale_order_id": self.id})
        action["context"] = base_ctx

        # normalize + extend domain
        dom = action.get("domain") or []
        if isinstance(dom, str):
            dom = safe_eval(dom) or []
        dom += [("sale_order_id", "=", self.id)]
        action["domain"] = dom
        return action

    # ----------------------------
    # Dispatch actions
    # ----------------------------
    def action_trakka_create_dispatch(self):
        """
        Create dispatch(es) for this SO:
        - Requires an existing escrow in 'held'
        - Creates ONE dispatch per outgoing Delivery Order (stock.picking) that lacks a dispatch
        """
        self.ensure_one()
        Escrow = self.env["trakka.payguard.escrow"].sudo()
        Dispatch = self.env["trakka.dispatch.order"].sudo().with_company(self.company_id)

        esc = Escrow.search([("sale_order_id", "=", self.id)], limit=1)
        if not esc:
            raise ValidationError(_("Create an Escrow first."))
        if esc.state != "held":
            raise ValidationError(_("Escrow must be in 'Held' to create dispatch(es). Current state: %s") %
                                  dict(esc._fields["state"].selection).get(esc.state))

        # Get all outgoing pickings for this SO
        outgoing_pickings = self.picking_ids.filtered(lambda p: p.picking_type_id.code == "outgoing")
        if not outgoing_pickings:
            raise UserError(_("No Delivery Orders found for this Sales Order."))

        created = self.env["trakka.dispatch.order"]
        for p in outgoing_pickings:
            exists = Dispatch.search([("picking_id", "=", p.id)], limit=1)
            if exists:
                continue
            created |= Dispatch.create({
                "picking_id": p.id,
                "company_id": p.company_id.id,
                "provider_type": "internal",
            })

        # Open what we created (or the list if multiple / already existed)
        action = {
            "type": "ir.actions.act_window",
            "name": _("Dispatch Orders"),
            "res_model": "trakka.dispatch.order",
            "view_mode": "tree,form",
            "target": "current",
            "domain": [("sale_order_id", "=", self.id)],
            "context": {"default_picking_id": False},
        }
        if len(created) == 1:
            action["res_id"] = created.id
            action["view_mode"] = "form,tree"
        return action

    def action_trakka_view_dispatch(self):
        """Smart button → open dispatches filtered to this SO."""
        self.ensure_one()

        action = None
        for xmlid in ("trakka.action_trakka_dispatch_orders",):
            try:
                action = self.env["ir.actions.act_window"]._for_xml_id(xmlid)
                break
            except Exception:
                action = None

        if not action:
            action = {
                "type": "ir.actions.act_window",
                "name": _("Dispatch Orders"),
                "res_model": "trakka.dispatch.order",
                "view_mode": "tree,form",
                "target": "current",
            }

        # normalize + extend context
        base_ctx = action.get("context") or {}
        if isinstance(base_ctx, str):
            try:
                base_ctx = safe_eval(base_ctx) or {}
            except Exception:
                base_ctx = {}
        base_ctx.update({"search_default_sale_order": self.id})
        action["context"] = base_ctx

        # normalize + extend domain
        dom = action.get("domain") or []
        if isinstance(dom, str):
            try:
                dom = safe_eval(dom) or []
            except Exception:
                dom = []
        dom += [("sale_order_id", "=", self.id)]
        action["domain"] = dom

        return action

    # ---------- Invoicing for delivered qty ----------
    def _trakka_invoice_delivered_qty(self, dispatch=None, post=True):
        """
        Create invoice(s) for delivered quantities only.

        Safe to call multiple times:
          - If already fully invoiced or nothing is invoiceable -> returns empty recordset.
          - Otherwise creates draft invoice(s) and posts them if post=True.

        :param dispatch: optional trakka.dispatch.order (for logging)
        :param post: bool, post created invoices when True
        :return: account.move recordset (possibly empty)
        """
        self.ensure_one()

        # Fast exit if SO already fully invoiced
        if self.invoice_status == "invoiced":
            return self.env["account.move"]

        # Only real lines (no sections/notes) that still have something to invoice
        invoiceable_lines = self.order_line.filtered(
            lambda l: not l.display_type and l.qty_to_invoice > 0
        )
        if not invoiceable_lines:
            # Nothing to invoice -> quiet no-op
            return self.env["account.move"]

        # Create invoices for delivered quantities
        moves = self.with_context(move_type="out_invoice")._create_invoices(final=True)

        if post:
            for mv in moves:
                if mv.state == "draft":
                    mv.action_post()

        self.message_post(
            body=_("Auto-invoiced delivered quantities%s.")
                 % (f" (dispatch: {dispatch.name})" if dispatch else "")
        )
        return moves