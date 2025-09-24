# master_addons/trakka_suite/trakka/models/connector_job.py
# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
import json
import hashlib
import hmac
import time

class TrakkaConnectorJob(models.Model):
    _name = "trakka.connector.job"
    _description = "3PL Outbound Job (retry queue)"
    _order = "id desc"

    name = fields.Char(default="3PL Job", required=True)
    connector_id = fields.Many2one("trakka.delivery.connector", required=True, ondelete="cascade")
    endpoint = fields.Selection(
        [("create", "Create Shipment"), ("track", "Track"), ("cancel", "Cancel")],
        required=True,
    )
    dispatch_id = fields.Many2one("trakka.dispatch.order")
    payload_json = fields.Text()
    tries = fields.Integer(default=0)
    last_error = fields.Text()
    state = fields.Selection(
        [("pending", "Pending"), ("done", "Done"), ("error", "Error")],
        default="pending", index=True,
    )

    def run(self, limit=50):
        """Manual/run by cron: attempt pending jobs."""
        to_run = self.search([("state", "=", "pending")], limit=limit)
        for job in to_run:
            try:
                job._run_one()
                job.write({"state": "done", "last_error": False})
            except Exception as e:
                job.write({"tries": job.tries + 1, "last_error": str(e)})
                # backoff: if too many tries, park as error
                if job.tries >= 5:
                    job.state = "error"

    def _run_one(self):
        """Delegate to the connector implementation via the base proxy."""
        connector = self.connector_id
        Impl = connector._get_impl()  # raises if misconfigured
        payload = {}
        try:
            payload = json.loads(self.payload_json or "{}")
        except Exception:
            pass

        if self.endpoint == "create":
            ref = Impl.create_shipment(self.dispatch_id)
            self.dispatch_id.write({"provider_ref": ref})
        elif self.endpoint == "track":
            res = Impl.track(payload.get("provider_ref") or self.dispatch_id.provider_ref)
            self.dispatch_id._apply_provider_status(res)
        elif self.endpoint == "cancel":
            Impl.cancel(payload.get("provider_ref") or self.dispatch_id.provider_ref)
        else:
            raise ValidationError(_("Unknown endpoint: %s") % (self.endpoint,))
