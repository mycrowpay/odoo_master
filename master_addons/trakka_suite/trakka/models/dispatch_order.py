from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

class TrakkaDispatchOrder(models.Model):
    _name = "trakka.dispatch.order"
    _description = "Dispatch Order"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(default=lambda s: s.env["ir.sequence"].next_by_code("trakka.dispatch.order"), readonly=True)
    sale_order_id = fields.Many2one("sale.order", required=True, check_company=True, index=True)
    company_id = fields.Many2one(related="sale_order_id.company_id", store=True, readonly=True)
    seller_id = fields.Many2one(related="sale_order_id.company_id", store=True, readonly=True)
    currency_id = fields.Many2one(related="sale_order_id.currency_id", store=True, readonly=True)

    buyer_name = fields.Char(required=True)
    buyer_phone = fields.Char(required=True)

    pickup_address = fields.Char(required=True)
    dropoff_address = fields.Char(required=True)
    distance_km = fields.Float()
    weight_kg = fields.Float()

    quoted_fee = fields.Monetary(currency_field="currency_id")
    provider_type = fields.Selection([
        ("trakka_rider", "Trakka Rider"),
        ("private_pl", "Private Provider"),
        ("3pl_partner", "3PL Partner"),
    ], default="trakka_rider", required=True)

    assigned_partner_id = fields.Many2one("res.partner", domain=[("is_company", "=", False)])
    state = fields.Selection([
        ("new", "New"),
        ("assigned", "Assigned"),
        ("accepted", "Accepted"),
        ("picked", "Picked"),
        ("on_route", "On Route"),
        ("delivered", "Delivered"),
        ("failed", "Failed"),
    ], default="new", tracking=True, index=True)

    delivered_at = fields.Datetime(readonly=True)
    proof_type = fields.Selection([("otp", "OTP"), ("photo", "Photo"), ("signature", "Signature")])
    proof_value = fields.Char()
    rating = fields.Integer()
    idempotency_key = fields.Char(index=True)

    def _require_assigned(self):
        if not self.assigned_partner_id:
            raise ValidationError(_("Assign a rider/provider first."))

    def action_assign(self):
        for r in self.filtered(lambda x: x.state == "new"):
            r._require_assigned()
            r.state = "assigned"

    def action_accept(self):
        self.filtered(lambda x: x.state == "assigned").write({"state": "accepted"})

    def action_pick(self):
        self.filtered(lambda x: x.state in ("accepted", "assigned")).write({"state": "picked"})

    def action_on_route(self):
        self.filtered(lambda x: x.state == "picked").write({"state": "on_route"})

    def action_delivered(self):
        for r in self:
            if r.state not in ("on_route", "picked", "accepted"):
                continue
            if not r.proof_type or not r.proof_value:
                raise ValidationError(_("Provide proof (OTP/Photo/Signature) before delivering."))
            r.write({"state": "delivered", "delivered_at": fields.Datetime.now()})
            r._after_delivered()

    def _after_delivered(self):
        for r in self:
            escrow = self.env["trakka.payguard.escrow"].search([("sale_order_id", "=", r.sale_order_id.id)], limit=1)
            if escrow and escrow.state == "held":
                escrow.action_set_release_ready()
            r.message_post(body=_("Delivered. Escrow marked Release Ready."))
