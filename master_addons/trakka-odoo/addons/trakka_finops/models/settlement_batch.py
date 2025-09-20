# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class TrakkaSettlementBatch(models.Model):
    _name = "trakka.settlement.batch"
    _description = "Trakka Settlement Batch"
    _order = "id desc"
    _check_company_auto = True

    name = fields.Char(required=True, default=lambda s: s._default_name())

    # NEW: date & state to match your views
    date = fields.Date(required=True, default=fields.Date.today, index=True)
    state = fields.Selection(
        [("draft", "Draft"), ("done", "Done")],
        default="draft",
        required=True,
        index=True,
    )

    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )

    escrow_ids = fields.One2many(
        "trakka.payguard.escrow",
        "settlement_batch_id",
        readonly=True,
    )

    line_count = fields.Integer(compute="_compute_line_count", store=False)

    def _default_name(self):
        return self.env["ir.sequence"].next_by_code("trakka.settlement.batch") or "Settlement"

    @api.depends("escrow_ids")
    def _compute_line_count(self):
        for b in self:
            b.line_count = len(b.escrow_ids)

    # cron entry point
    @api.model
    def _cron_settle_released_ready(self, limit=200):
        escrows = self.env["trakka.payguard.escrow"].search([
            ("state", "=", "released_ready"),
            ("company_id", "=", self.env.company.id),
        ], limit=limit)
        if not escrows:
            return 0
        batch = self.create({})
        for e in escrows:
            e._post_settlement_move(batch)
        _logger.info("Settlement batch %s processed %s escrows", batch.id, len(escrows))
        return len(escrows)
