# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
import json

class TrakkaDispatchOrder(models.Model):
    _name = "trakka.dispatch.order"
    _description = "Dispatch Order"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    # --- identity / linkage ---
    name = fields.Char(
        string="Dispatch Ref",
        readonly=True,
        copy=False,
        default=lambda s: s.env["ir.sequence"].next_by_code("trakka.dispatch.order"),
        tracking=True,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda s: s.env.company,
        index=True,
    )

    # Primary: Delivery Order
    picking_id = fields.Many2one(
        "stock.picking",
        string="Delivery Order",
        required=True,
        index=True,
        domain="[('picking_type_id.code','=','outgoing'), '|', ('company_id','=', False), ('company_id','=', company_id)]",
        tracking=True,
        help="Outbound Delivery this dispatch coordinates.",
    )

    # Secondary (derived)
    sale_order_id = fields.Many2one(
        "sale.order",
        string="Sales Order",
        related="picking_id.sale_id",
        store=True,
        readonly=True,
        index=True,
        tracking=True,
    )

        # 3PL connector integration
    connector_id = fields.Many2one(
        "trakka.delivery.connector",
        string="Connector",
        help="External delivery provider integration to use for this dispatch.",
    )
    provider_ref = fields.Char(
        string="Provider Reference",
        readonly=True,
        copy=False,
        help="Reference/ID returned by the external provider when the shipment is created.",
    )
    provider_status_json = fields.Text(
        string="Provider Status (JSON)",
        readonly=True,
        copy=False,
        help="Raw status payload from the provider.",
    )


    # Escrow helper (computed)
    escrow_id = fields.Many2one(
        "trakka.payguard.escrow",
        compute="_compute_escrow_id",
        string="Escrow",
        readonly=True,
    )

    # >>> NEW: Related views of the picking’s moves and move lines <<<
    picking_move_ids = fields.One2many(
        "stock.move",
        "picking_id",
        string="Delivery Moves",
        related="picking_id.move_ids",
        readonly=True,
    )
    picking_move_line_ids = fields.One2many(
        "stock.move.line",
        "picking_id",
        string="Delivery Move Lines",
        related="picking_id.move_line_ids",
        readonly=True,
    )

    # --- assignment / routing / quoting / proof / state (unchanged from your last) ---
    provider_type = fields.Selection(
        [("internal", "Internal Fleet"), ("3pl", "3rd Party"), ("gig", "Gig (Rider)")],
        string="Provider Type",
        default="internal",
        tracking=True,
        required=True,
    )
    assigned_partner_id = fields.Many2one(
        "res.partner",
        string="Assigned To",
        domain="[('type','!=','private')]",
        help="Rider / Driver / 3PL partner taking this job.",
        tracking=True,
    )
    buyer_contact_name = fields.Char(string="Buyer Name")
    buyer_contact_phone = fields.Char(string="Buyer Phone")
    pickup_address = fields.Char()
    dropoff_address = fields.Char()

    distance_km = fields.Float(string="Distance (km)")
    weight_kg = fields.Float(string="Weight (kg)")
    quoted_fee = fields.Monetary(
        string="Quoted Fee",
        currency_field="currency_id",
        help="Estimated delivery fee.",
        readonly=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        related="company_id.currency_id",
        store=True,
        readonly=True,
    )

    proof_type = fields.Selection(
        [("none", "None"), ("otp", "OTP"), ("signature", "Signature"), ("photo", "Photo")],
        default="none",
        required=True,
        string="Proof Type",
        tracking=True,
    )
    proof_value = fields.Char(string="Proof Value / OTP")
    delivered_at = fields.Datetime(readonly=True)
    fail_reason = fields.Text(string="Failure Reason")
    rating = fields.Selection(
        [(str(i), str(i)) for i in range(1, 6)],
        string="Delivery Rating",
        help="1 (worst) .. 5 (best)",
    )

    state = fields.Selection(
        [
            ("new", "New"),
            ("assigned", "Assigned"),
            ("accepted", "Accepted"),
            ("picked", "Picked"),
            ("on_route", "On Route"),
            ("delivered", "Delivered"),
            ("failed", "Failed"),
        ],
        default="new",
        tracking=True,
        index=True,
    )

    _sql_constraints = [
        ("uniq_dispatch_per_picking", "unique(picking_id)", "A Dispatch already exists for this Delivery Order."),
    ]

    # --- computes / guards / onchange / pricing helpers (as you had) ---
    @api.depends("sale_order_id")
    def _compute_escrow_id(self):
        Escrow = self.env["trakka.payguard.escrow"].sudo()
        for rec in self:
            rec.escrow_id = False
            if rec.sale_order_id:
                esc = Escrow.search([("sale_order_id", "=", rec.sale_order_id.id)], limit=1)
                rec.escrow_id = esc.id if esc else False

    @api.model
    def create(self, vals):
        picking_id = vals.get("picking_id")
        if not picking_id:
            raise ValidationError(_("Dispatch must be linked to a Delivery Order (stock.picking)."))

        picking = self.env["stock.picking"].browse(picking_id)
        if not picking or picking.picking_type_id.code != "outgoing":
            raise ValidationError(_("Dispatch can only be created for an outgoing Delivery Order."))

        if picking.company_id and vals.get("company_id") and picking.company_id.id != vals["company_id"]:
            raise ValidationError(_("Dispatch company must match the Delivery Order company."))

        so = picking.sale_id
        if not so:
            raise ValidationError(_("The Delivery Order is not linked to a Sales Order."))

        escrow = self.env["trakka.payguard.escrow"].sudo().search([("sale_order_id", "=", so.id)], limit=1)
        if not escrow:
            raise ValidationError(_("Create an Escrow for the Sales Order before creating a Dispatch."))
        if escrow.state != "held":
            raise ValidationError(_("Escrow must be in 'Held' to create a Dispatch."))

        vals.setdefault("company_id", picking.company_id.id or self.env.company.id)

        rec = super().create(vals)
        rec._prefill_from_picking()
        return rec

    def _prefill_from_picking(self):
        for rec in self:
            so = rec.sale_order_id
            partner = so.partner_id if so else False
            if partner:
                rec.buyer_contact_name = rec.buyer_contact_name or partner.display_name
                phone = partner.mobile or partner.phone or ""
                rec.buyer_contact_phone = rec.buyer_contact_phone or phone
            if so and not rec.pickup_address:
                rec.pickup_address = (
                    so.warehouse_id
                    and so.warehouse_id.partner_id
                    and so.warehouse_id.partner_id.contact_address
                ) or ""
            if partner and not rec.dropoff_address:
                rec.dropoff_address = partner.contact_address or ""
            rec._compute_quoted_fee()

    @api.onchange("picking_id")
    def _onchange_picking_id(self):
        for rec in self:
            if rec.picking_id and rec.picking_id.company_id:
                rec.company_id = rec.picking_id.company_id
            rec._prefill_from_picking()

    @api.onchange("distance_km", "weight_kg", "provider_type")
    def _onchange_quote_inputs(self):
        for rec in self:
            rec._compute_quoted_fee()

    def _compute_quoted_fee(self):
        for rec in self:
            amount = 0.0
            if "trakka.pricing.rule" in self.env:
                rules = self.env["trakka.pricing.rule"].sudo().search(
                    [("company_id", "in", [False, rec.company_id.id])], limit=1
                )
                if rules:
                    amount = rules.compute_price(
                        distance_km=rec.distance_km or 0.0,
                        weight_kg=rec.weight_kg or 0.0,
                        provider_type=rec.provider_type,
                        sale_order=rec.sale_order_id,
                    )
            if not amount:
                amount = (rec.distance_km or 0.0) * 50.0 + (rec.weight_kg or 0.0) * 10.0
            rec.quoted_fee = amount

    def _ensure_states(self, allowed):
        for rec in self:
            if rec.state not in allowed:
                raise UserError(
                    _("Operation not allowed from state: %s")
                    % dict(self._fields["state"].selection).get(rec.state, rec.state)
                )

    def action_assign(self):
        self._ensure_states({"new"})
        for rec in self:
            if not rec.assigned_partner_id:
                raise ValidationError(_("Please set 'Assigned To' before assigning."))
            rec.state = "assigned"
            rec.message_post(body=_("Dispatch assigned to %s.") % rec.assigned_partner_id.display_name)

    def action_accept(self):
        self._ensure_states({"assigned"})
        for rec in self:
            rec.state = "accepted"
            rec.message_post(body=_("Assignment accepted."))

    def action_pick(self):
        self._ensure_states({"accepted"})
        for rec in self:
            rec.state = "picked"
            rec.message_post(body=_("Order picked."))

    def action_on_route(self):
        self._ensure_states({"picked"})
        for rec in self:
            rec.state = "on_route"
            rec.message_post(body=_("Rider is on route."))

    def _try_validate_picking(self):
        for rec in self:
            picking = rec.picking_id.sudo()
            if not picking or picking.state in ("done", "cancel"):
                continue
            try:
                result = picking.button_validate()
                if isinstance(result, dict):
                    rec.message_post(
                        body=_("Delivery validation requires a warehouse step (wizard). "
                               "Please complete the Delivery Order: %s") % (picking.name,)
                    )
                else:
                    rec.message_post(body=_("Delivery Order %s validated.") % (picking.name,))
            except Exception as e:
                rec.message_post(body=_("Attempt to validate Delivery Order %s failed: %s") % (picking.name, e))

    def action_deliver(self):
        self._ensure_states({"on_route"})
        for rec in self:
            # Proof checks
            if rec.proof_type == "otp" and not rec.proof_value:
                raise ValidationError(_("Enter the OTP in 'Proof Value' before delivering."))

            # Guards on picking / serials
            picking = rec.picking_id
            if not picking:
                raise ValidationError(_("No delivery picking is linked to this dispatch."))
            if picking.state != "done":
                raise ValidationError(_("The linked picking must be validated (Done) before marking delivered."))

            for ml in picking.move_line_ids:
                if ml.product_id.tracking != "none" and not ml.lot_id:
                    raise ValidationError(
                        _("Tracked product %(prod)s requires a lot/serial before delivery.")
                        % {"prod": ml.product_id.display_name}
                    )

            # ---- Try to invoice delivered qty (safe no-op if nothing to invoice) ----
            try:
                invoices = rec.sale_order_id._trakka_invoice_delivered_qty(dispatch=rec, post=True)
            except UserError as e:
                # Extra safety: if some module still raises the classic "no items to invoice", ignore
                msg = (getattr(e, 'name', '') or str(e)).lower()
                if "no items are available to invoice" in msg or "no lines" in msg:
                    invoices = rec.env["account.move"]
                else:
                    raise

            # Company policy: require invoice before settlement
            if rec.company_id.trakka_require_invoice_before_settlement:
                if rec.sale_order_id.invoice_status != "invoiced":
                    raise ValidationError(
                        _("Company policy requires invoicing before marking Delivered. "
                          "Create/post the invoice for delivered products, then try again.")
                    )

            # ---- Mark delivered ----
            rec.state = "delivered"
            rec.delivered_at = fields.Datetime.now()
            rec.message_post(body=_("Delivered successfully. %s") % (
                invoices and _("Invoice(s): %s") % ", ".join(invoices.mapped("name")) or _("No new invoices created")
            ))

            # ---- Escrow: move to Release Ready automatically if policy allows ----
            Escrow = self.env["trakka.payguard.escrow"].sudo()
            escrow = Escrow.search([("sale_order_id", "=", rec.sale_order_id.id)], limit=1)
            if escrow and escrow.state == "held" and escrow.release_policy in ("auto_on_delivery", "auto_after_cooldown"):
                try:
                    escrow.action_set_release_ready()
                except Exception as e:
                    escrow.message_post(body=_("Auto move to Release Ready failed on delivery: %s") % e)



    def action_fail(self):
        self._ensure_states({"new", "assigned", "accepted", "picked", "on_route"})
        for rec in self:
            if not rec.fail_reason:
                raise ValidationError(_("Please provide a failure reason before marking as failed."))
            rec.state = "failed"
            rec.message_post(body=_("Delivery failed: %s") % rec.fail_reason)

    # Smart: open the Delivery Order
    def action_open_picking(self):
        self.ensure_one()
        if not self.picking_id:
            raise ValidationError(_("No Delivery Order linked."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Delivery Order"),
            "res_model": "stock.picking",
            "view_mode": "form,tree",
            "target": "current",
            "res_id": self.picking_id.id,
        }

    def action_open_attachments(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Attachments"),
            "res_model": "ir.attachment",
            "view_mode": "kanban,tree,form",
            "domain": [("res_model", "=", self._name), ("res_id", "=", self.id)],
            "context": {
                "default_res_model": self._name,
                "default_res_id": self.id,
                "search_default_my_attachments": 0,
            },
            "target": "current",
        }
    
        # --- 3PL connector linkage ---
    connector_id = fields.Many2one(
        "trakka.delivery.connector",
        string="Delivery Connector",
        help="Optional 3PL / Rider-app connector to send this dispatch to.",
        tracking=True,
    )
    provider_ref = fields.Char(
        string="Provider Reference",
        readonly=True,
        copy=False,
        help="External reference returned by the provider."
    )
    provider_status_json = fields.Json(string="Provider Status (raw)", readonly=True)


    def action_send_to_provider(self):
        """Create shipment on the chosen connector and store provider_ref."""
        for rec in self:
            if not rec.connector_id:
                raise ValidationError(_("Please select a Delivery Connector first."))
            if rec.provider_ref:
                raise ValidationError(_("This dispatch is already sent to a provider (%s).") % rec.provider_ref)
            if rec.state not in ("new", "assigned", "accepted"):
                raise ValidationError(_("You can only send a dispatch while it's New/Assigned/Accepted."))

            payload = rec.connector_id.create_shipment(rec)
            if not isinstance(payload, dict) or not payload.get("provider_ref"):
                raise UserError(_("Connector did not return a provider_ref."))
            rec.provider_ref = payload["provider_ref"]
            if payload.get("raw"):
                rec.provider_status_json = payload["raw"]
            rec.message_post(body=_("Sent to provider %s → %s") % (rec.connector_id.code, rec.provider_ref))
        return True

    def action_refresh_status(self):
        """Call connector.track and map state/events into the dispatch."""
        for rec in self:
            if not rec.connector_id or not rec.provider_ref:
                raise ValidationError(_("No connector/provider_ref to refresh."))
            tracking = rec.connector_id.track(rec.provider_ref)
            rec.connector_id._apply_provider_status_to_dispatch(rec, tracking)
        return True
    

        # inside trakka.dispatch.order class
    def _apply_provider_status(self, payload):
        """Update fields from provider payload; keep raw trail."""
        for rec in self:
            # append/replace raw json
            raw = (rec.provider_status_json or "").strip()
            if raw:
                try:
                    current = json.loads(raw)
                except Exception:
                    current = {}
            else:
                current = {}
            # naive merge for demo
            for k, v in (payload or {}).items():
                current[k] = v
            rec.provider_status_json = json.dumps(current, indent=2)

            # map status → state if present
            status = (payload or {}).get("status")
            if status == "accepted" and rec.state == "assigned":
                rec.state = "accepted"
            elif status in ("in_transit", "picked") and rec.state in ("accepted", "assigned", "picked"):
                rec.state = "picked"
            elif status in ("out_for_delivery", "on_route") and rec.state in ("accepted", "picked", "on_route"):
                rec.state = "on_route"
            elif status == "delivered":
                if rec.state not in ("delivered",):
                    rec.state = "delivered"
            elif status == "failed":
                rec.state = "failed"

    


        # ----------------------------
    # 3PL: outbound calls
    # ----------------------------
    def action_send_to_provider(self):
        """Create shipment on the selected connector and store provider_ref."""
        for rec in self:
            if not rec.connector_id:
                raise ValidationError(_("Select a Connector before sending to provider."))
            if rec.provider_ref:
                raise ValidationError(_("This dispatch is already registered with the provider (ref: %s).") % rec.provider_ref)

            # Calls the abstract connector; real connectors override create_shipment
            provider_ref = rec.connector_id.create_shipment(rec)
            if not provider_ref:
                raise UserError(_("Connector did not return a provider reference."))

            rec.write({"provider_ref": provider_ref})
            rec.message_post(body=_("Sent to provider. Reference: %s") % provider_ref)

    def action_refresh_provider_status(self):
        """Poll provider for latest status; store payload & optionally sync state."""
        for rec in self:
            if not rec.connector_id:
                raise ValidationError(_("No Connector configured on this dispatch."))
            if not rec.provider_ref:
                raise ValidationError(_("No provider reference yet. Send to provider first."))

            payload = rec.connector_id.track(rec.provider_ref) or {}
            # Save raw payload
            try:
                rec.provider_status_json = json.dumps(payload, ensure_ascii=False, indent=2)
            except Exception:
                # fall back to string
                rec.provider_status_json = str(payload)

            # Optional: map external status to our state
            new_state = rec._map_provider_status_to_state(payload)
            if new_state and new_state != rec.state:
                # allow only forward moves
                allowed = {
                    "new": {"assigned"},
                    "assigned": {"accepted", "picked", "failed"},
                    "accepted": {"picked", "failed"},
                    "picked": {"on_route", "failed"},
                    "on_route": {"delivered", "failed"},
                    "delivered": set(),
                    "failed": set(),
                }
                if rec.state in allowed and new_state in allowed[rec.state]:
                    getattr(rec, f"action_{'on_route' if new_state=='on_route' else new_state}")()
                else:
                    rec.message_post(body=_("Provider suggests state '%s' but transition was ignored.") % new_state)

            rec.message_post(body=_("Provider status refreshed."))

    # ----------------------------
    # 3PL: status mapping helper
    # ----------------------------
    def _map_provider_status_to_state(self, payload):
        """Translate provider payload to one of our states."""
        status = (payload.get("status") or payload.get("state") or "").lower()
        mapping = {
            "created": "assigned",
            "assigned": "assigned",
            "accepted": "accepted",
            "picked": "picked",
            "in_transit": "on_route",
            "on_route": "on_route",
            "delivered": "delivered",
            "failed": "failed",
            "canceled": "failed",
        }
        return mapping.get(status)



