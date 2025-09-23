# -*- coding: utf-8 -*-
from odoo import models
from datetime import timedelta
from odoo import fields


class TrakkaDeliveryConnectorFake(models.Model):
    _name = "trakka.delivery.connector.fake"
    _description = "Fake Connector (Demo)"
    _inherit = "trakka.delivery.connector.mixin"

    def quote(self, so=None, dispatch=None):
        amount = 2500.0
        eta = (fields.Datetime.now() + timedelta(days=2)).isoformat()
        return {"amount": amount, "eta": eta, "provider": "FAKE"}

    def create_shipment(self, dispatch):
        return f"FAKE-{dispatch.id}"

    def track(self, provider_ref):
        # rotate simple statuses for demo
        return {"status": "in_transit", "provider_ref": provider_ref}

    def cancel(self, provider_ref):
        return True
