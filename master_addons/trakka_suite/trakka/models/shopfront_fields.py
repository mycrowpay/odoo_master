# -*- coding: utf-8 -*-
from odoo import api, fields, models

class ResPartner(models.Model):
    _inherit = "res.partner"
    shop_slug = fields.Char(string="Shopfront Slug", index=True)

class ProductProduct(models.Model):
    _inherit = "product.product"
    shop_publish = fields.Boolean(string="Publish to Shopfront", default=True, index=True)
