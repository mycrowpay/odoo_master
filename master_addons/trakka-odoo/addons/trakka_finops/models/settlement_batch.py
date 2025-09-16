# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from datetime import datetime

class TrakkaSettlementBatch(models.Model):
    _name = "trakka.settlement.batch"
    _description = "Nightly Settlement Batch"
    _order = "id desc"

    name = fields.Char(required=True)
    line_count = fields.Integer()
    posted_move_ids = fields.Many2many("account.move", string="Posted Journal Entries")

    @api.model
    def cron_nightly_settlement(self):
        """ir.cron entry point. Create a batch and settle all released_ready escrows."""
        batch = self.create({"name": f"SET {fields.Datetime.now()}"})
        escrows = self.env["trakka.payguard.escrow"].search([("state", "=", "released_ready")])
        posted_moves = self.env["account.move"]
        for esc in escrows:
            move = esc._post_settlement_move(batch)
            posted_moves |= move
        batch.write({"line_count": len(posted_moves), "posted_move_ids": [(6, 0, posted_moves.ids)]})
        return batch.id
