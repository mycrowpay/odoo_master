# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class TrakkaDeliveryPricingRule(models.Model):
    _name = "trakka.delivery.pricing.rule"
    _description = "Delivery Pricing Rule (v1)"
    _order = "sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda s: s.env.company, index=True
    )
    city = fields.Char(help="Free-text city match (case-insensitive). Leave empty for any city.")

    base_fee = fields.Monetary(required=True, default=0.0)
    per_km = fields.Monetary(required=True, default=0.0)
    per_kg = fields.Monetary(required=True, default=0.0)
    mult_time_slot = fields.Float(string="% Time Slot Multiplier", help="e.g. 10 for +10%")
    mult_peak = fields.Float(string="% Peak Multiplier", help="e.g. 20 for +20%")
    min_fee = fields.Monetary()
    max_fee = fields.Monetary()

    currency_id = fields.Many2one(
        "res.currency",
        related="company_id.currency_id",
        store=True,
        readonly=True,
    )

    active = fields.Boolean(default=True)

    @api.model
    def compute_quote(self, *, company, city, distance_km=0.0, weight_kg=0.0, when=None, peak=False):
        """Return a (rule, fee) tuple; rule may be False if no match."""
        Rule = self.with_company(company).sudo()
        dom = [("active", "=", True), ("company_id", "=", company.id)]
        # city filter is optional; match with ilike if provided
        rules = Rule.search(dom, order="sequence, id")
        picked = False
        fee = 0.0
        for r in rules:
            if r.city and city:
                if r.city.strip().lower() not in (city or "").strip().lower():
                    continue
            elif r.city:  # rule has city but SO doesn't
                continue
            picked = r
            fee = (r.base_fee or 0.0) + (distance_km or 0.0) * (r.per_km or 0.0) + (weight_kg or 0.0) * (r.per_kg or 0.0)
            if r.mult_time_slot:
                fee *= (1.0 + (r.mult_time_slot / 100.0))
            if peak and r.mult_peak:
                fee *= (1.0 + (r.mult_peak / 100.0))
            if r.min_fee:
                fee = max(fee, r.min_fee)
            if r.max_fee:
                fee = min(fee, r.max_fee)
            break
        return picked, fee
