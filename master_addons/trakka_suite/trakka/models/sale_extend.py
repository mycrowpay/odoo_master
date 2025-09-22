# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

class SaleOrder(models.Model):
    _inherit = "sale.order"

    # Smart-button counters
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

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------
    def action_trakka_create_escrow(self):
        """Create (or open) an escrow for this SO."""
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
        """Smart button → list escrows for this SO."""
        self.ensure_one()
        action = self.env.ref("trakka.action_trakka_escrows").read()[0]
        action["domain"] = [("sale_order_id", "=", self.id)]
        action.setdefault("context", {})
        action["context"].update({
            "default_sale_order_id": self.id,
            "default_company_id": self.company_id.id,
        })
        return action

    def action_trakka_view_dispatch(self):
        """Smart button → list dispatch orders for this SO."""
        self.ensure_one()
        action = self.env.ref("trakka.action_trakka_dispatch_orders").read()[0]
        action["domain"] = [("sale_order_id", "=", self.id)]
        action.setdefault("context", {})
        action["context"].update({
            "default_sale_order_id": self.id,
            "default_company_id": self.company_id.id,
        })
        return action
