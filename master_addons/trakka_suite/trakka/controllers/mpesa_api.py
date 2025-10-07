# -*- coding: utf-8 -*-
from odoo import http, _
from odoo.http import request
import json

class TrakkaMpesaApi(http.Controller):
    @http.route("/payments/mpesa/stk/init", type="json", auth="public", methods=["POST"], csrf=False)
    def stk_init(self, **kwargs):
        """
        Body: { "so_id": 123, "phone": "2547xxxxxxxx" }
        Returns: { "ok": true, "psp_ref": "..." }
        """
        data = request.jsonrequest or {}
        so_id = int(data.get("so_id") or 0)
        phone = (data.get("phone") or "").strip()
        if not so_id or not phone:
            return {"ok": False, "error": "missing_params"}
        so = request.env["sale.order"].sudo().browse(so_id)
        if not so.exists():
            return {"ok": False, "error": "so_not_found"}

        intent = request.env["trakka.mpesa.intent"].sudo().create_for_checkout(so, phone)
        intent.sudo().action_stk_push()
        return {"ok": True, "psp_ref": intent.psp_ref}

    @http.route("/webhooks/mpesa", type="json", auth="public", methods=["POST"], csrf=False)
    def webhook_mpesa(self, **kwargs):
        """
        Expect Daraja-ish payload. For stub we accept:
        { "psp_ref": "STK-1", "result_code": 0, "payload": {...} }
        """
        data = request.jsonrequest or {}
        psp_ref = data.get("psp_ref")
        result_code = int(data.get("result_code") or 1)
        payload = data.get("payload")
        if not psp_ref:
            return {"ok": False, "error": "no_ref"}

        if result_code == 0:
            request.env["trakka.mpesa.intent"].sudo().mark_funded(psp_ref, payload)
            return {"ok": True}
        else:
            # mark failed if you like
            intent = request.env["trakka.mpesa.intent"].sudo().search([("psp_ref","=",psp_ref)], limit=1)
            if intent:
                intent.write({"state": "failed", "raw_last": json.dumps(payload or {})})
            return {"ok": False, "error": "failed"}
