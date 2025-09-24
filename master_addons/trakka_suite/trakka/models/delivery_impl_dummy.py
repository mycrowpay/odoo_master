# -*- coding: utf-8 -*-
from odoo import models

class TrakkaDeliveryImplDummy(models.AbstractModel):
    _name = "trakka.delivery.impl.dummy"
    _description = "Dummy Delivery Connector Implementation"

    # required API
    def quote(self, so=None, dispatch=None):
        return {"amount": 100.0, "eta": "P2D"}

    def create_shipment(self, dispatch):
        return f"DEMOPROV-{dispatch.id}"

    def track(self, provider_ref):
        return {"status": "in_transit", "events": [{"status": "picked"}]}

    def cancel(self, provider_ref):
        return True
