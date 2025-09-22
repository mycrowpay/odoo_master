# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.tools.safe_eval import safe_eval
from odoo.exceptions import ValidationError, UserError


class SaleOrder(models.Model):
    _inherit = "sale.order"

    trakka_escrow_count = fields.Integer(compute="_compute_trakka_counts", store=False)
    trakka_dispatch_count = fields.Integer(compute="_compute_trakka_counts", store=False)

    # Flags for UI visibility/guards
    trakka_has_escrow = fields.Boolean(compute="_compute_trakka_escrow_flags", store=False)
    trakka_escrow_state = fields.Selection(
        [("held", "Held"), ("released_ready", "Release Ready"), ("released", "Released")],
        compute="_compute_trakka_escrow_flags",
        store=False,
    )

    def _compute_trakka_counts(self):
        escrow_rg = self.env["trakka.payguard.escrow"].read_group(
            [("sale_order_id", "in", self.ids)], ["sale_order_id"], ["sale_order_id"]
        )
        esc_map = {r["sale_order_id"][0]: r["sale_order_id_count"] for r in escrow_rg}

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
            so.trakka_has_escrow = False
            so.trakka_escrow_state = False
            esc = Escrow.search([("sale_order_id", "=", so.id)], limit=1)
            if esc:
                so.trakka_has_escrow = True
                so.trakka_escrow_state = esc.state

    # -------- Escrow --------
    def action_trakka_create_escrow(self):
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
        self.ensure_one()

        action = None
        for xmlid in (
            "trakka.action_trakka_escrow",
            "trakka.action_trakka_escrows",
            "trakka.action_payguard_escrows",
        ):
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

        base_ctx = action.get("context") or {}
        if isinstance(base_ctx, str):
            base_ctx = safe_eval(base_ctx) or {}
        base_ctx.update({"default_sale_order_id": self.id})
        action["context"] = base_ctx

        dom = action.get("domain") or []
        if isinstance(dom, str):
            dom = safe_eval(dom) or []
        dom += [("sale_order_id", "=", self.id)]
        action["domain"] = dom
        return action

    # -------- Dispatch (manual, gated by escrow) --------
    def action_trakka_create_dispatch(self):
        """Create a dispatch only if an escrow exists and is 'held'."""
        self.ensure_one()
        Escrow = self.env["trakka.payguard.escrow"].sudo()
        Dispatch = self.env["trakka.dispatch.order"].with_company(self.company_id).sudo()

        esc = Escrow.search([("sale_order_id", "=", self.id)], limit=1)
        if not esc:
            raise ValidationError(_("Create an Escrow before creating a Dispatch for this Sales Order."))
        if esc.state != "held":
            raise ValidationError(_("Dispatch can be created only when the Escrow is in 'Held' state."))

        # Respect the unique constraint: one dispatch per SO
        existing = Dispatch.search([("sale_order_id", "=", self.id)], limit=1)
        if existing:
            return existing.get_formview_action()

        dsp = Dispatch.create({
            "sale_order_id": self.id,
            "company_id": self.company_id.id,
        })
        return dsp.get_formview_action()

    def action_trakka_view_dispatch(self):
        self.ensure_one()

        action = None
        for xmlid in (
            "trakka.action_trakka_dispatch_orders",
            "trakka.action_dispatch_orders",
        ):
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

        base_ctx = action.get("context") or {}
        if isinstance(base_ctx, str):
            try:
                base_ctx = safe_eval(base_ctx) or {}
            except Exception:
                base_ctx = {}
        base_ctx.update({"default_sale_order_id": self.id})
        action["context"] = base_ctx

        dom = action.get("domain") or []
        if isinstance(dom, str):
            try:
                dom = safe_eval(dom) or []
            except Exception:
                dom = []
        dom += [("sale_order_id", "=", self.id)]
        action["domain"] = dom

        return action

    # IMPORTANT: no auto-dispatch on confirm anymore
    # def action_confirm(self):
    #     res = super().action_confirm()
    #     return res
