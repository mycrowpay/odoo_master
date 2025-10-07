# -*- coding: utf-8 -*-
from odoo import models, fields

class ProductTemplateShopFlag(models.Model):
    _inherit = "product.template"
    shop_publish = fields.Boolean(string="Publish on Shopfront", default=False)
