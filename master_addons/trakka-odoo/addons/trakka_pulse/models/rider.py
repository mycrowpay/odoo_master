from odoo import fields, models

class TrakkaPulseRider(models.Model):
    _name = "trakka.pulse.rider"
    _description = "Rider (external; no Odoo seat)"

    name = fields.Char(required=True)
    phone = fields.Char()
    partner_id = fields.Many2one("res.partner", help="Optional link to external entity")
