# -*- coding: utf-8 -*-
import re
import uuid
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
            if rec.shop_slug:
                # only [a-z0-9-] allowed
                candidate = rec.shop_slug
                cleaned = _SLUG_RE.sub('-', candidate).strip('-')
                if cleaned != candidate or not cleaned:
                    raise ValidationError(_("Shop slug can only contain lowercase letters, digits and hyphens."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Only generate for companies (seller concept)
            is_company = vals.get('is_company') or (vals.get('company_type') == 'company')
            if is_company and not vals.get('shop_slug'):
                base = _slugify(vals.get('name')) or str(uuid.uuid4())[:8]
                vals['shop_slug'] = self._generate_unique_slug(base)
        records = super().create(vals_list)
        return records

    def write(self, vals):
        # If user manually sets a slug, normalize & ensure uniqueness
        if 'shop_slug' in vals and vals.get('shop_slug'):
            base = _slugify(vals['shop_slug'])
            if not base:
                raise ValidationError(_("Invalid slug"))
            vals = dict(vals)  # copy
            # resolve uniqueness against all others (excluding each self)
            for rec in self:
                vals['shop_slug'] = rec._generate_unique_slug(base, exclude_id=rec.id)
                super(ResPartner, rec).write(vals)
            return True

        res = super().write(vals)

        # If slug got cleared explicitly on a company, regenerate
        if 'shop_slug' in vals and not vals.get('shop_slug'):
            for rec in self:
                if rec.is_company or rec.company_type == 'company':
                    base = _slugify(rec.name) or str(uuid.uuid4())[:8]
                    rec.shop_slug = rec._generate_unique_slug(base)
        return res

    def _generate_unique_slug(self, base, exclude_id=False):
        """Ensure uniqueness by suffixing -2, -3, ... if needed."""
        base = base or 'company'
        slug = base
        i = 2
        Partner = self.env['res.partner'].sudo()
        while True:
            domain = [('shop_slug', '=', slug)]
            if exclude_id:
                domain.append(('id', '!=', exclude_id))
            if Partner.search_count(domain) == 0:
                return slug
            slug = f"{base}-{i}"
            i += 1
