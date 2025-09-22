from odoo import api, fields, models

class TrakkaDeliveryPricingRule(models.Model):
    _name = "trakka.delivery.pricing.rule"
    _description = "Delivery Pricing Rule"

    name = fields.Char(required=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda s: s.env.company)
    city = fields.Char(required=True)
    base_fee = fields.Monetary(required=True)
    per_km = fields.Monetary(required=True)
    per_kg = fields.Monetary(required=True)
    slot_multiplier = fields.Float(default=1.0)
    peak_multiplier = fields.Float(default=1.0)
    min_fee = fields.Monetary(default=0.0)
    max_fee = fields.Monetary(default=0.0)
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id", store=True)

    def compute_quote(self, distance_km, weight_kg, at_dt=None):
        self.ensure_one()
        amt = (self.base_fee or 0.0) + (self.per_km or 0.0) * (distance_km or 0.0) + (self.per_kg or 0.0) * (weight_kg or 0.0)
        amt *= (self.slot_multiplier or 1.0) * (self.peak_multiplier or 1.0)
        if self.min_fee and amt < self.min_fee:
            amt = self.min_fee
        if self.max_fee and self.max_fee > 0 and amt > self.max_fee:
            amt = self.max_fee
        return amt
