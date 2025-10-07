# -*- coding: utf-8 -*-
from odoo import models, fields

class PartnerSellerSlug(models.Model):
    _inherit = "res.partner"
    shop_slug = fields.Char(string="Shopfront Slug", help="Public slug used by the shopfront API.")
