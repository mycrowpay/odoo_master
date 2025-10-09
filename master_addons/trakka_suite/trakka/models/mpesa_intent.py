# -*- coding: utf-8 -*-
import json
import logging
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from ..services.mpesa_daraja import daraja

_logger = logging.getLogger(__name__)

class TrakkaMpesaIntent(models.Model):
    _name = "trakka.mpesa.intent"
    _description = "MPesa STK Intent"
    _order = "id desc"

    name = fields.Char(default=lambda s: _("MPesa %s") % fields.Datetime.now(), readonly=True)
    company_id = fields.Many2one("res.company", default=lambda s: s.env.company, required=True)
    sale_order_id = fields.Many2one("sale.order", required=True, index=True)
    escrow_id = fields.Many2one("trakka.payguard.escrow", index=True)
    amount = fields.Monetary(required=True, currency_field="currency_id")
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id", store=True, readonly=True)
    phone = fields.Char(required=True)
    psp_ref = fields.Char(index=True)
    idempotency_key = fields.Char(index=True)
    state = fields.Selection([
        ("init","Init"),("pending","Pending"),
        ("funded","Funded"),("failed","Failed")
    ], default="init", index=True)
    raw_last = fields.Text()

    @api.model
    def _make_idem(self, so_id, amount, phone):
        src = f"{so_id}:{amount}:{phone}"
        import hashlib
        return hashlib.sha256(src.encode("utf-8")).hexdigest()

    @api.model
    def create_for_checkout(self, so, phone):
        if so.amount_total <= 0:
            raise ValidationError(_("Order amount must be positive."))
        idem = self._make_idem(so.id, so.amount_total, phone)
        existing = self.search([("idempotency_key","=",idem)], limit=1)
        if existing:
            return existing
        esc = self.env["trakka.payguard.escrow"].sudo().search([("sale_order_id","=",so.id)], limit=1)
        if not esc:
            esc = self.env["trakka.payguard.escrow"].sudo().create({"sale_order_id": so.id, "amount": so.amount_total})
        return self.create({
            "sale_order_id": so.id,
            "escrow_id": esc.id,
            "amount": so.amount_total,
            "phone": phone,
            "idempotency_key": idem,
        })

    def action_stk_push(self):
        """
        Run STK push. Returns a dict:
          { ok: bool, psp_ref: str|None, error: str|None, payload: dict }
        Also updates record state/psp_ref/raw_last.
        """
        results = []
        for rec in self:
            dj = daraja(self.env)
            # Dummy mode handled inside client; always returns ok=True
            res = dj.stk_push(
                amount=rec.amount,
                msisdn=rec.phone,
                psp_ref_hint=f"SO{rec.sale_order_id.id}"
            )
            # Save last payload for debug
            try:
                rec.raw_last = json.dumps(res.get("payload") or {}, ensure_ascii=False)
            except Exception:
                rec.raw_last = str(res.get("payload"))

            if res.get("ok"):
                rec.state = "pending"
                if res.get("psp_ref"):
                    rec.psp_ref = res["psp_ref"]
                elif not rec.psp_ref:
                    rec.psp_ref = f"STK-{rec.id}"
            else:
                rec.state = "failed"
                _logger.error("M-Pesa STK failed for intent %s: %s", rec.id, res.get("error"))

            results.append({
                "ok": bool(res.get("ok")),
                "psp_ref": rec.psp_ref or None,
                "error": res.get("error"),
                "state": rec.state,
            })
        return results[0] if len(results) == 1 else results

    def mark_funded(self, psp_ref, raw_payload=None):
        rec = self.search([("psp_ref","=",psp_ref)], limit=1)
        if not rec:
            return False
        if raw_payload:
            try:
                rec.raw_last = json.dumps(raw_payload, ensure_ascii=False)
            except Exception:
                rec.raw_last = str(raw_payload)
        if rec.state == "funded":
            return True
        rec.state = "funded"
        esc = rec.escrow_id.sudo()
        if esc:
            esc.write({"fund_state": "funded"})
            esc.message_post(body=_("MPesa funded via %s.") % psp_ref)
        return True
