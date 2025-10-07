# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
import base64, hashlib, json, datetime

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
    psp_ref = fields.Char(index=True)            # CheckoutRequestID
    idempotency_key = fields.Char(index=True)    # (so_id, amount, phone) hash
    state = fields.Selection([("init","Init"),("pending","Pending"),("funded","Funded"),("failed","Failed")], default="init", index=True)
    raw_last = fields.Text()

    @api.model
    def _make_idem(self, so_id, amount, phone):
        src = f"{so_id}:{amount}:{phone}"
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

    # Wire to Daraja here in real impl; stub returns a pseudo ref
    def action_stk_push(self):
        for rec in self:
            rec.state = "pending"
            rec.psp_ref = rec.psp_ref or f"STK-{rec.id}"
            rec.raw_last = json.dumps({"stub": True, "psp_ref": rec.psp_ref})
        return True

    # Called by webhook; idempotent
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
        # Flip escrow → funded (add the field below in escrow model)
        esc = rec.escrow_id.sudo()
        if esc:
            esc.write({"fund_state": "funded"})
            esc.message_post(body=_("MPesa funded via %s.") % psp_ref)
        return True
