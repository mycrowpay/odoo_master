# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.tools.safe_eval import safe_eval


class SaleOrder(models.Model):
    _inherit = "sale.order"

    trakka_escrow_count = fields.Integer(compute="_compute_trakka_counts", store=False)
    trakka_dispatch_count = fields.Integer(compute="_compute_trakka_counts", store=False)

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

    # Header button: create or open escrow (enforced 1-per-SO by SQL constraint)
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

    # Smart buttons
    def action_trakka_view_escrows(self):
        self.ensure_one()

        # Try a few likely XMLIDs; fall back to a generic action if none found
        action = None
        for xmlid in (
            "trakka.action_trakka_escrows",
            "trakka.action_payguard_escrows",
            "trakka.action_trakka_payguard_escrows",
        ):
            try:
                action = self.env["ir.actions.act_window"]._for_xml_id(xmlid)
                break
            except Exception:
                action = None

        if not action:
            # Build a vanilla action if the xmlid can't be resolved
            action = {
                "type": "ir.actions.act_window",
                "name": _("Escrows"),
                "res_model": "trakka.payguard.escrow",
                "view_mode": "tree,form",
                "target": "current",
            }

        # Normalize & merge context (may be a string)
        base_ctx = action.get("context") or {}
        if isinstance(base_ctx, str):
            base_ctx = safe_eval(base_ctx) or {}
        ctx = dict(self.env.context)
        ctx.update(base_ctx)
        ctx.update({"default_sale_order_id": self.id})
        action["context"] = ctx

        # Normalize & extend domain (may be a string)
        dom = action.get("domain") or []
        if isinstance(dom, str):
            dom = safe_eval(dom) or []
        dom = dom + [("sale_order_id", "=", self.id)]
        action["domain"] = dom

        return action

    def action_trakka_view_dispatch(self):
        self.ensure_one()

        # Try our dispatch action XMLID; fall back to a plain action
        action = None
        for xmlid in (
            "trakka.action_trakka_dispatch_orders",     # <- matches your dispatch_views.xml
            "trakka.action_dispatch_orders",            # optional fallback guesses
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

        # --- normalize context (may be a string) and extend it
        base_ctx = action.get("context") or {}
        if isinstance(base_ctx, str):
            try:
                base_ctx = safe_eval(base_ctx) or {}
            except Exception:
                base_ctx = {}
        base_ctx.update({
            "default_sale_order_id": self.id,
        })
        action["context"] = base_ctx

        # --- normalize domain (may be a string) and extend it
        dom = action.get("domain") or []
        if isinstance(dom, str):
            try:
                dom = safe_eval(dom) or []
            except Exception:
                dom = []
        dom += [("sale_order_id", "=", self.id)]
        action["domain"] = dom

        return action
    

    def _trakka_ensure_dispatch(self):
        Dispatch = self.env["trakka.dispatch.order"].with_company(self.company_id)
        for so in self:
            exists = Dispatch.search([("sale_order_id", "=", so.id)], limit=1)
            if exists:
                continue
            Dispatch.create({
                "sale_order_id": so.id,
                "company_id": so.company_id.id,
                # distance/weight can be computed later; pricing will still run
            })

    def action_confirm(self):
        res = super().action_confirm()
        # Create dispatch(es) for confirmed orders
        self._trakka_ensure_dispatch()
        return res
