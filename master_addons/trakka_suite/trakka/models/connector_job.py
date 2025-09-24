# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
import json
from datetime import datetime

class TrakkaConnectorJob(models.Model):
    _name = "trakka.connector.job"
    _description = "3PL Connector Job Queue"
    _order = "next_run_at asc, id asc"

    state = fields.Selection([
        ("queued", "Queued"),
        ("done", "Done"),
        ("failed", "Failed"),
    ], default="queued", index=True)
    connector_id = fields.Many2one("trakka.delivery.connector", required=True, ondelete="cascade")
    job_type = fields.Selection([
        ("create_shipment", "Create Shipment"),
        ("track", "Track"),
        ("cancel", "Cancel"),
        ("generic", "Generic"),
    ], required=True)
    payload_json = fields.Text(help="JSON payload for the job")
    attempt = fields.Integer(default=0)
    error_message = fields.Text()
    next_run_at = fields.Datetime(default=lambda self: fields.Datetime.now(), index=True)

    @api.model
    def run(self, limit=50):
        """Cron entrypoint: pick due jobs and process them."""
        now = fields.Datetime.now()
        jobs = self.search([
            ("state", "=", "queued"),
            ("next_run_at", "<=", now),
        ], limit=limit)
        for job in jobs:
            job._process_one()

    def _process_one(self):
        self.ensure_one()
        impl = self.connector_id._get_impl()
        payload = {}
        if self.payload_json:
            try:
                payload = json.loads(self.payload_json)
            except Exception:
                pass

        try:
            if self.job_type == "create_shipment":
                dispatch = self.env["trakka.dispatch.order"].browse(payload.get("dispatch_id"))
                impl.create_shipment(dispatch)
            elif self.job_type == "track":
                ref = payload.get("provider_ref")
                impl.track(ref)
            elif self.job_type == "cancel":
                ref = payload.get("provider_ref")
                impl.cancel(ref)
            else:
                # generic no-op
                pass

            self.write({"state": "done", "error_message": False})
        except Exception as e:
            # backoff: 5, 15, 60 minutes …
            self.attempt += 1
            delay = [5, 15, 60, 180][min(self.attempt - 1, 3)]
            self.write({
                "state": "queued",
                "error_message": str(e),
                "next_run_at": fields.Datetime.to_string(
                    fields.Datetime.now() + fields.timedelta(minutes=delay)
                ),
            })
