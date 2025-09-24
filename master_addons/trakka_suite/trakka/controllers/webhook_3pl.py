# master_addons/trakka_suite/trakka/controllers/webhook_3pl.py
# -*- coding: utf-8 -*-
from odoo import http, _
from odoo.http import request
import json, hmac, hashlib, time

class Trakka3PLWebhook(http.Controller):

    @http.route("/trakka/3pl/callback", type="json", auth="public", methods=["POST"], csrf=False)
    def callback(self, **kwargs):
        """
        Expected JSON:
        {
          "provider": "shadowship",
          "provider_ref": "SHADOW-123",
          "timestamp": 1699999999,
          "payload": {...},
          "signature": "hex(hmac_sha256(webhook_secret, body))"
        }
        """
        body = request.httprequest.data or b""
        try:
            data = json.loads(body.decode("utf-8"))
        except Exception:
            return {"ok": False, "error": "invalid_json"}

        provider = (data.get("provider") or "").strip().lower()
        provider_ref = data.get("provider_ref")
        ts = int(data.get("timestamp") or 0)
        sig = (data.get("signature") or "").strip()

        if not provider or not provider_ref or not ts or not sig:
            return {"ok": False, "error": "missing_fields"}

        # Replay protection (5 minutes)
        if abs(time.time() - ts) > 300:
            return {"ok": False, "error": "stale_timestamp"}

        dispatch = request.env["trakka.dispatch.order"].sudo().search(
            [("provider_ref", "=", provider_ref)], limit=1
        )
        if not dispatch:
            return {"ok": False, "error": "dispatch_not_found"}

        connector = dispatch.connector_id.sudo()
        secret = (connector.webhook_secret or "").encode("utf-8")
        expect = hmac.new(secret, body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expect, sig):
            return {"ok": False, "error": "bad_signature"}

        # Let the adapter interpret payload if needed; here we just trust "payload"
        payload = data.get("payload") or {}
        dispatch.sudo()._apply_provider_status(payload)
        return {"ok": True}
