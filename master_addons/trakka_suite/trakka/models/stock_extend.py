# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class StockPicking(models.Model):
    _inherit = "stock.picking"

    picking_type_code = fields.Selection(related="picking_type_id.code", store=False)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for p in records:
            if p.picking_type_id.code != "outgoing" or not p.sale_id:
                continue
            # Create a dispatch per picking if none exists
            Dispatch = self.env["trakka.dispatch.order"].sudo().with_company(p.company_id)
            exists = Dispatch.search([("picking_id", "=", p.id)], limit=1)
            if not exists:
                # Optional: only spawn a dispatch if an escrow exists and is in 'held'
                escrow = self.env["trakka.payguard.escrow"].sudo().search([("sale_order_id", "=", p.sale_id.id)], limit=1)
                if escrow and escrow.state == "held":
                    Dispatch.create({
                        "picking_id": p.id,
                        "company_id": p.company_id.id,
                        "provider_type": "internal",
                    })
        return records

    def button_validate(self):
        res = super().button_validate()
        # After inventory is moved (done), poke escrow policy
        for p in self:
            if p.state != "done" or p.picking_type_id.code != "outgoing" or not p.sale_id:
                continue
            escrow = self.env["trakka.payguard.escrow"].sudo().search(
                [("sale_order_id", "=", p.sale_id.id)], limit=1
            )
            if escrow:
                escrow._try_mark_release_ready(trigger="picking")
        return res
