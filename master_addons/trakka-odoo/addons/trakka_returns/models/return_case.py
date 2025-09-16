# -*- coding: utf-8 -*-
from odoo import fields, models

class TrakkaReturnCase(models.Model):
    _name = "trakka.return.case"
    _description = "Trakka Return Case"

    name = fields.Char(required=True)
    sale_order_id = fields.Many2one("sale.order", index=True)
    policy_id = fields.Many2one("trakka.policy")
    reason = fields.Selection([
        ("defect", "Defect"),
        ("remorse", "Buyer Remorse"),
        ("other", "Other"),
    ])
    # Store object keys only (signing done outside Odoo)
    evidence_keys = fields.Text(
        help="JSON array of S3/MinIO object keys provided by Gateway"
    )
