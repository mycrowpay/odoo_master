# -*- coding: utf-8 -*-
import re
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_SLUG_RE = re.compile(r'[^a-z0-9]+')

def _slugify(text):
    text = (text or "").strip().lower()
    text = _SLUG_RE.sub('-', text).strip('-')
    return text or None

class ResPartner(models.Model):
    _inherit = "res.partner"

    shop_slug = fields.Char(
        string="Shop Slug",
        index=True,
        copy=False,
        help="Public slug used by the shopfront API to identify the seller."
    )

    _sql_constraints = [
        # allow multiple blanks (NULL), but enforce uniqueness when set
        ('shop_slug_unique', 'unique(shop_slug)', 'This shop slug is already used.')
    ]

    @api.constrains('shop_slug')
    def _check_shop_slug_format(self):
        for rec in self:
            if rec.shop_slug and _SLUG_RE.sub('', rec.shop_slug) != rec.shop_slug.replace('-', ''):
                # Only [a-z0-9-] allowed after our slugify; guard against manual bad edits
                raise ValidationError(_("Shop slug can only contain lowercase letters, digits and hyphens."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Only generate for companies (seller concept)
            is_company = vals.get('is_company') or (vals.get('company_type') == 'company')
            if is_company and not vals.get('shop_slug'):
                base = _slugify(vals.get('name'))
                vals['shop_slug'] = self._generate_unique_slug(base)
        records = super().create(vals_list)
        return records

    def write(self, vals):
        # If someone clears the slug on a company, regenerate
        res = super().write(vals)
        regen_needed = 'shop_slug' in vals and not vals.get('shop_slug')
        if regen_needed:
            for rec in self:
                if rec.is_company or rec.company_type == 'company':
                    base = _slugify(rec.name)
                    rec.shop_slug = rec._generate_unique_slug(base)
        return res

    def _generate_unique_slug(self, base):
        """Ensure uniqueness by suffixing -2, -3, ... if needed."""
        base = base or 'company'
        slug = base
        i = 2
        while self.env['res.partner'].sudo().search_count([('shop_slug', '=', slug)]) > 0:
            slug = f"{base}-{i}"
            i += 1
        return slug
