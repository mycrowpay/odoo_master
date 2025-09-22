from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

class TrakkaSettlementBatch(models.Model):
    _name = "trakka.settlement.batch"
    _description = "Settlement Batch"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(default=lambda s: _("Batch %s") % fields.Datetime.now(), readonly=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda s: s.env.company)
    escrow_ids = fields.Many2many("trakka.payguard.escrow")
    state = fields.Selection([("draft", "Draft"), ("done", "Done")], default="draft", tracking=True)

    def action_process(self):
        for b in self:
            ready = b.escrow_ids.filtered(lambda e: e.state == "released_ready")
            if not ready:
                raise ValidationError(_("No 'Release Ready' escrows in batch."))
            for e in ready:
                e.with_company(b.company_id).action_post_settlement_move()
            b.state = "done"
        return True

    @api.model
    def cron_process_ready_escrows(self):
        companies = self.env["res.company"].search([])
        for c in companies:
            escrows = self.env["trakka.payguard.escrow"].with_company(c).search([("state", "=", "released_ready")], limit=50)
            if escrows:
                batch = self.create({"company_id": c.id, "escrow_ids": [(6, 0, escrows.ids)]})
                batch.action_process()
