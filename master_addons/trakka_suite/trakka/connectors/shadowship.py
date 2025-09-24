# master_addons/trakka_suite/trakka/connectors/shadowship.py
# -*- coding: utf-8 -*-
from odoo import models, _
from odoo.exceptions import ValidationError
import json
from datetime import datetime

class TrakkaConnectorShadowShip(models.AbstractModel):
    _name = "trakka.connector.shadowship"
    _description = "ShadowShip 3PL Connector (example)"
    _inherit = "trakka.delivery.connector.mixin"

    # Helper to fetch the attached trakka.delivery.connector record from context
    def _get_cfg(self):
        connector_id = self.env.context.get("connector_id")
        connector = self.env["trakka.delivery.connector"].browse(connector_id)
        if not connector or not connector.exists():
            raise ValidationError(_("ShadowShip: missing connector context."))
        return connector

    # ---- API expected by the mixin / base proxy ----
    def quote(self, so=None, dispatch=None):
        """Pretend to call provider and return amount & eta."""
        # super simple demo: fee = 100 + 10 * weight
        weight = getattr(dispatch, "weight_kg", 0.0) or 0.0
        fee = 100.0 + 10.0 * weight
        # ISO 8601 “duration-ish” hint for UI
        return {"amount": round(fee, 2), "eta": "P1D"}

    def create_shipment(self, dispatch):
        """Pretend to create a shipment and return a provider reference."""
        cfg = self._get_cfg()
        # In real life you'd POST to cfg.extra_config (base_url) with cfg.api_key, etc.
        ref = f"SHADOW-{dispatch.id}"
        # return provider ref (the base model will store it on the dispatch)
        return ref

    def track(self, provider_ref):
        """Return current status payload (idempotent)."""
        # Demo status flips based on current time seconds just to show motion
        sec = int(datetime.utcnow().strftime("%S"))
        if sec % 10 < 3:
            status = "accepted"
        elif sec % 10 < 6:
            status = "in_transit"
        elif sec % 10 < 8:
            status = "out_for_delivery"
        else:
            status = "delivered"

        return {
            "provider_ref": provider_ref,
            "status": status,
            "events": [{"ts": "now", "msg": f"ShadowShip status: {status}"}],
        }

    def cancel(self, provider_ref):
        """Pretend to cancel; return boolean success."""
        return True
