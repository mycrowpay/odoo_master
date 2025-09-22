# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


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
    sale_order_id = fields.Many2one(
        "sale.order",
        string="Sales Order",
        required=True,
        index=True,
        check_company=True,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        help="SO to be delivered by this dispatch.",
        tracking=True,
    )

    # Optional seller (merchant) side — keep label distinct from 'Company'
    seller_id = fields.Many2one(
        "res.partner",
        string="Seller",
        help="Merchant / Seller associated to the order, if applicable.",
        index=True,
    )

    # --- dispatch assignment ---
    provider_type = fields.Selection(
        [
            ("internal", "Internal Fleet"),
            ("3pl", "3rd Party"),
            ("gig", "Gig (Rider)"),
        ],
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

    # --- consignee / routing ---
    buyer_contact_name = fields.Char(string="Buyer Name")
    buyer_contact_phone = fields.Char(string="Buyer Phone")
    pickup_address = fields.Char()
    dropoff_address = fields.Char()

    # --- logistics metrics / quoting ---
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

    # --- proof of delivery ---
    proof_type = fields.Selection(
        [
            ("none", "None"),
            ("otp", "OTP"),
            ("signature", "Signature"),
            ("photo", "Photo"),
        ],
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

    # --- states ---
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
    )

    # ----------------------------
    # Constraints / SQL-level
    # ----------------------------
    _sql_constraints = [
        (
            "uniq_so_dispatch",
            "unique(sale_order_id)",
            "Each Sales Order can only be linked to one Dispatch Order.",
        ),
    ]

    # ----------------------------
    # Onchanges / Defaults
    # ----------------------------
    @api.onchange("sale_order_id")
    def _onchange_sale_order_id(self):
        for rec in self:
            so = rec.sale_order_id
            if not so:
                continue

            # Keep company aligned with the SO (and respect check_company)
            if so.company_id and rec.company_id != so.company_id:
                rec.company_id = so.company_id

            # Prefill consignee info from SO partner
            partner = so.partner_id
            if partner:
                rec.buyer_contact_name = rec.buyer_contact_name or partner.display_name
                # prefer mobile over phone
                phone = partner.mobile or partner.phone or ""
                rec.buyer_contact_phone = rec.buyer_contact_phone or phone

            # Prefill addresses — customize to your data model as needed
            # If you have stock.picking addresses, map accordingly; here we fall back to partner addresses.
            if not rec.pickup_address:
                rec.pickup_address = (so.warehouse_id and so.warehouse_id.partner_id and so.warehouse_id.partner_id.contact_address) or ""
            if not rec.dropoff_address:
                rec.dropoff_address = partner and partner.contact_address or ""

            # Quick & safe quote recompute
            rec._compute_quoted_fee()

    @api.onchange("distance_km", "weight_kg", "provider_type")
    def _onchange_quote_inputs(self):
        for rec in self:
            rec._compute_quoted_fee()

    def _compute_quoted_fee(self):
        """Very simple quoting. If a pricing model exists (trakka.pricing.rule),
        try to use it; otherwise fallback to a basic formula."""
        for rec in self:
            amount = 0.0
            # Try optional pricing engine if your module implements it
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
                # Fallback: simple linear quote
                amount = (rec.distance_km or 0.0) * 50.0 + (rec.weight_kg or 0.0) * 10.0
            rec.quoted_fee = amount

    # ----------------------------
    # Actions: lifecycle
    # ----------------------------
    def _ensure_states(self, allowed):
        for rec in self:
            if rec.state not in allowed:
                raise UserError(
                    _("Operation not allowed from state: %s") % dict(self._fields["state"].selection).get(rec.state, rec.state)
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

    def action_deliver(self):
        self._ensure_states({"on_route"})
        for rec in self:
            # Proof checks
            if rec.proof_type == "otp" and not rec.proof_value:
                raise ValidationError(_("Enter the OTP in 'Proof Value' before delivering."))
            rec.state = "delivered"
            rec.delivered_at = fields.Datetime.now()
            rec.message_post(body=_("Delivered successfully."))

    def action_fail(self):
        # Allow failing from any non-terminal state except delivered/failed
        self._ensure_states({"new", "assigned", "accepted", "picked", "on_route"})
        for rec in self:
            if not rec.fail_reason:
                raise ValidationError(_("Please provide a failure reason before marking as failed."))
            rec.state = "failed"
            rec.message_post(body=_("Delivery failed: %s") % rec.fail_reason)

    # ----------------------------
    # Attachments helper (for stat button)
    # ----------------------------
    def action_open_attachments(self):
        """Open ir.attachment filtered on this dispatch record."""
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
