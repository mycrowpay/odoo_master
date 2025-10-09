# -*- coding: utf-8 -*-
import json
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

class TrakkaMpesaApi(http.Controller):
    # CORS preflight (shared)
    @http.route(['/payments/mpesa/stk/init', '/webhooks/mpesa'], type='http',
                auth='public', methods=['OPTIONS'], csrf=False, cors="*")
    def preflight(self, **kwargs):
        return request.make_response('', headers=[
            ('Access-Control-Allow-Origin', '*'),
            ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
            ('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Requested-With'),
            ('Access-Control-Max-Age', '86400'),
        ])

    # --- STK init: keep as JSON ------------------------------------------------
    @http.route("/payments/mpesa/stk/init", type="json", auth="public",
                methods=["POST"], csrf=False, cors="*")
    def stk_init(self, **kwargs):
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
        return {"ok": intent.state != "failed",
                "psp_ref": intent.psp_ref,
                "state": intent.state}

    # --- Helper to read JSON from a type='http' request ------------------------
    def _json_from_http(self):
        try:
            raw = request.httprequest.get_data(cache=False, as_text=True) or ''
            return json.loads(raw) if raw else {}
        except Exception:
            _logger.exception("Webhook: invalid JSON body")
            return {}

    # --- Webhook: MUST be type='http' (Daraja posts raw HTTP JSON) -------------
    @http.route("/webhooks/mpesa", type="http", auth="public",
                methods=["POST"], csrf=False, cors="*")
    def webhook_mpesa(self, **kwargs):
        """
        Accept both:
          1) Dummy/test: {"psp_ref":"...","result_code":0,"payload":{...}}
          2) Real Daraja: {"Body":{"stkCallback":{"CheckoutRequestID":"...","ResultCode":0,...}}}
        """
        data = self._json_from_http()

        psp_ref = data.get("psp_ref")
        result_code = data.get("result_code")
        payload = data.get("payload")

        # Real Daraja?
        if not payload and data.get("Body"):
            payload = data
            stk = payload.get("Body", {}).get("stkCallback", {})
            result_code = stk.get("ResultCode")
            psp_ref = stk.get("CheckoutRequestID") or stk.get("MerchantRequestID")

        if not psp_ref:
            body = json.dumps({"ok": False, "error": "no_ref"})
            return request.make_response(body, headers=[('Content-Type', 'application/json')], status=400)

        try:
            rc = int(result_code)
        except Exception:
            rc = 1

        if rc == 0:
            request.env["trakka.mpesa.intent"].sudo().mark_funded(psp_ref, payload)
            body = json.dumps({"ok": True})
            return request.make_response(body, headers=[('Content-Type', 'application/json')], status=200)
        else:
            intent = request.env["trakka.mpesa.intent"].sudo().search([("psp_ref", "=", psp_ref)], limit=1)
            if intent:
                intent.write({"state": "failed", "raw_last": json.dumps(payload or {})})
            body = json.dumps({"ok": False, "error": "failed", "psp_ref": psp_ref})
            return request.make_response(body, headers=[('Content-Type', 'application/json')], status=200)
