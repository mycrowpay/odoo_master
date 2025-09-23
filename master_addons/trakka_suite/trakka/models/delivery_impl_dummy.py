# -*- coding: utf-8 -*-
from odoo import models, _

class TrakkaConnectorDummy(models.AbstractModel):
    """
    Minimal connector implementation so you can wire a connector record to it.
    Replace with real 3PL adapters later (e.g., trakka.connector.gig, trakka.connector.sendy, etc.).
    """
    _name = "trakka.connector.dummy"
    _description = "Dummy Delivery Connector (always succeeds)"

    # --- required API ---
    def quote(self, so=None, dispatch=None):
        # return a flat 10.00 with "1 day" ETA
        return {"amount": 10.0, "eta": "P1D"}

    def create_shipment(self, dispatch):
        # pretend we created a shipment and return a provider reference
        return f"DUMMY-{dispatch.id}"

    def track(self, provider_ref):
        # return a fake status payload
        return {
            "provider_ref": provider_ref,
            "status": "in_transit",
            "events": [{"ts": "now", "msg": "Dummy in transit"}],
        }

    def cancel(self, provider_ref):
        # always allow cancel in dummy
        return True
