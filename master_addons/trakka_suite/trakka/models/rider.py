from odoo import api, fields, models

class TrakkaRider(models.Model):
    _name = "trakka.rider"
    _description = "Rider"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    partner_id = fields.Many2one("res.partner", required=True, domain=[("is_company","=",False)], ondelete="restrict")
    status = fields.Selection([("probation","Probation"),("active","Active"),("suspended","Suspended")], default="probation", tracking=True)
    score = fields.Float(digits=(16,2))
    completed_deliveries = fields.Integer()
    kyc_id_doc = fields.Binary()
    kyc_id_doc_filename = fields.Char()

    def cron_recompute_scores(self):
        for r in self.search([]):
            count = self.env["trakka.dispatch.order"].search_count([("assigned_partner_id","=",r.partner_id.id),("state","=","delivered")])
            r.completed_deliveries = count
            r.score = min(100.0, 50.0 + count * 1.5)
            if r.status == "probation" and r.completed_deliveries >= 30 and r.score >= 95.0:
                r.status = "active"
