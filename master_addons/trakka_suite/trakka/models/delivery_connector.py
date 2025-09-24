# -*- coding: utf-8 -*-
import json
import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class TrakkaDeliveryConnector(models.Model):
    _name = "trakka.delivery.connector"
    _description = "Delivery Connector (3PL/Carrier Adapter)"
    # If you want chatter on connectors, uncomment the next line
    # _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)

    # Pick the Python model (ir.model) that implements this connector
    implementation_model_id = fields.Many2one(
        "ir.model",
        string="Implementation Model",
        required=True,
        ondelete="cascade",
        # ONLY allow connector implementations
        domain=[("model", "ilike", "trakka.connector.%")],
        help="Pick the technical model that implements this connector "
             "(e.g., trakka.connector.dummy, trakka.connector.gig, ...).",
    )

    implementation_model = fields.Char(
        string="Technical Model Name",
        related="implementation_model_id.model",
        store=False,
        readonly=True,
    )

    # Optional configuration (per connector)
    api_key = fields.Char(groups="base.group_system")
    api_secret = fields.Char(groups="base.group_system")
    webhook_secret = fields.Char(groups="base.group_system")
    extra_config = fields.Text(help="JSON/YAML blob for provider-specific settings.")

    # -------------------------------------------------------------------------
    # Public API to be called by dispatch
    # -------------------------------------------------------------------------
    def quote(self, so=None, dispatch=None):
        """Return dict like {'amount': 123.45, 'eta': 'P2D'}"""
        impl = self._get_impl()
        return impl.quote(so=so, dispatch=dispatch)

    def create_shipment(self, dispatch):
        """Return provider_ref string"""
        impl = self._get_impl()
        return impl.create_shipment(dispatch)

    def track(self, provider_ref):
        """Return dict payload from provider (status, events, etc.)"""
        impl = self._get_impl()
        return impl.track(provider_ref)

    def cancel(self, provider_ref):
        """Return True/False"""
        impl = self._get_impl()
        return impl.cancel(provider_ref)

    # -------------------------------------------------------------------------
    # Cron: poll status for ongoing dispatches (called by Server Action / Cron)
    # -------------------------------------------------------------------------
    @api.model
    def cron_poll_status(self, limit=100):
        """
        Poll provider status for open dispatches and update their state.
        Safe to call from ir.actions.server (Server Action) or scheduler.
        """
        Dispatch = self.env["trakka.dispatch.order"]

        # Pick all dispatches that were pushed to a provider and aren't final
        dispatches = Dispatch.search([
            ("provider_ref", "!=", False),
            ("state", "not in", ["delivered", "failed"]),
        ], limit=limit)

        _logger.info("cron_poll_status: polling %s dispatches", len(dispatches))

        for d in dispatches:
            connector = d.connector_id
            if not connector:
                continue

            try:
                payload = connector.track(d.provider_ref) or {}
            except Exception as e:
                # Never let the cron crash — log and continue
                _logger.exception("Polling failed for dispatch %s (ref=%s): %s", d.id, d.provider_ref, e)
                self.env.cr.rollback()
                continue

            # Store raw payload for debugging (Text field => dump to JSON string)
            try:
                d.provider_status_json = json.dumps(payload, ensure_ascii=False)
            except Exception:
                # Fallback if payload isn't serializable
                d.provider_status_json = str(payload)

            # Map provider status to internal state
            new_state = self._map_provider_status(payload)
            if new_state and new_state != d.state:
                d.state = new_state

        _logger.info("cron_poll_status: done")

    # Small helper so partners can override mapping per connector later if needed
    @api.model
    def _map_provider_status(self, payload):
        """
        Map a provider payload to our internal dispatch state.
        Override if your provider returns different keys/values.
        """
        status = (payload.get("status") or "").lower()
        mapping = {
            "assigned": "assigned",
            "accepted": "accepted",
            "picked": "picked",
            "on_route": "on_route",
            "in_transit": "on_route",
            "delivered": "delivered",
            "failed": "failed",
            # add more aliases as needed
        }
        return mapping.get(status)

    # -------------------------------------------------------------------------
    # Internal helpers / guards
    # -------------------------------------------------------------------------
    def _get_impl(self):
        """Return the implementation recordset for this connector."""
        self.ensure_one()
        model = self.implementation_model_id.model
        if not model:
            raise ValidationError(_("Implementation model is not set."))
        ImplModel = self.env[model].with_context(connector_id=self.id)
        # must implement the mixin methods:
        for m in ("quote", "create_shipment", "track", "cancel"):
            if not hasattr(ImplModel, m):
                raise ValidationError(_("Model %s does not implement method %s()") % (model, m))
        return ImplModel

    def _check_inherits_connector(self, vals_list):
        """
        Validate that the chosen model exists and exposes the required methods.
        We must check the recordset (env[model_name]), not registry meta.
        """
        for vals in vals_list:
            impl_model_id = vals.get("implementation_model_id")
            if not impl_model_id:
                continue

            im = self.env["ir.model"].browse(impl_model_id)
            model_name = im.model or ""
            if not model_name:
                raise ValidationError(_("Implementation model is not set."))

            try:
                rs = self.env[model_name]
            except KeyError:
                raise ValidationError(_("Model %s is not loaded in registry.") % model_name)

            required = ("quote", "create_shipment", "track", "cancel")
            missing = [m for m in required if not hasattr(rs, m)]
            if missing:
                raise ValidationError(
                    _("Model %s does not implement required methods: %s") % (model_name, ", ".join(missing))
                )

    @api.model
    def create(self, vals):
        self._check_inherits_connector([vals])
        return super().create(vals)

    def write(self, vals):
        self._check_inherits_connector([vals])
        return super().write(vals)


# Optional mixin for implementors (nice for IDEs and readability)
class TrakkaDeliveryConnectorMixin(models.AbstractModel):
    _name = "trakka.delivery.connector.mixin"
    _description = "Mixin: Delivery Connector Implementation"

    def quote(self, so=None, dispatch=None):
        raise NotImplementedError("quote() must be implemented by the connector")

    def create_shipment(self, dispatch):
        raise NotImplementedError("create_shipment() must be implemented by the connector")

    def track(self, provider_ref):
        raise NotImplementedError("track() must be implemented by the connector")

    def cancel(self, provider_ref):
        raise NotImplementedError("cancel() must be implemented by the connector")
