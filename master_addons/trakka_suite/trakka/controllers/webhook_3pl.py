# -*- coding: utf-8 -*-
from odoo import http, _
from odoo.http import request
import json
import logging
import hmac
import hashlib

_logger = logging.getLogger(__name__)


class Trakka3PLWebhookController(http.Controller):
    """
    Inbound webhook endpoint for 3PL status updates.

    Expected JSON body example:
    {
      "connector_code": "bolt",
      "provider_ref": "REF123",
      "state": "on_route",
      "events": [{"ts": "...", "label": "Picked up"}],
      "raw": {...}  // optional entire provider payload
    }

    HMAC header: X-Trakka-Signature  (sha256 over raw request body using connector.hmac_secret)
    """

    @http.route("/trakka/3pl/callback", type="json", auth="public", methods=["POST"], csrf=False)
    def trakka_3pl_callback(self, **kwargs):
        raw = request.httprequest.data or b""
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            _logger.warning("3PL callback: invalid JSON")
            return {"ok": False, "error": "invalid_json"}

        connector_code = payload.get("connector_code")
        provider_ref = payload.get("provider_ref")
        if not connector_code or not provider_ref:
            return {"ok": False, "error": "missing_fields"}

        Connector = request.env["trakka.delivery.connector"].sudo().search(
            [("code", "=", connector_code), ("active", "=", True)], limit=1
        )
        if not Connector:
            return {"ok": False, "error": "unknown_connector"}

        # Verify HMAC
        signature = request.httprequest.headers.get("X-Trakka-Signature")
        if not signature or not Connector._verify_signature(raw, signature):
            _logger.warning("3PL callback: signature mismatch for %s", connector_code)
            return {"ok": False, "error": "bad_signature"}

        Dispatch = request.env["trakka.dispatch.order"].sudo()
        dsp = Dispatch.search([("provider_ref", "=", provider_ref), ("connector_id", "=", Connector.id)], limit=1)
        if not dsp:
            return {"ok": False, "error": "dispatch_not_found"}

        # Apply status
        Connector._apply_provider_status_to_dispatch(dsp, {
            "state": payload.get("state"),
            "events": payload.get("events"),
            "raw": payload.get("raw") or payload,
        })
        return {"ok": True}
