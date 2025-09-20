# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class TrakkaReversePickingWizard(models.TransientModel):
    _name = "trakka.reverse.picking.wizard"
    _description = "Reverse Picking Wizard (all items)"

    picking_id = fields.Many2one("stock.picking", required=True)

    def action_reverse_all(self):
        """Return all delivered quantities back to source (standard stock return)."""
        self.ensure_one()
        picking = self.picking_id
        if not picking or picking.state != "done":
            raise UserError(_("Only completed pickings can be reversed."))

        # Use stock.return.picking if available (standard wizard)
        Return = self.env["stock.return.picking"].with_context(
            active_id=picking.id, active_model="stock.picking"
        )
        ret = Return.create({"picking_id": picking.id})
        # populate lines (in v17 onchange will create move_ids with returned qty)
        ret._onchange_picking_id()

        # ensure we return full delivered qty for each move
        for ml in ret.move_ids:
            ml.quantity = ml.quantity  # keep suggested (delivered)

        res = ret.create_returns()
        # v17 returns an action; try to resolve res_id/new picking
        new_pick = None
        if isinstance(res, dict):
            rid = res.get("res_id")
            if rid:
                new_pick = self.env["stock.picking"].browse(rid)
        if not new_pick:
            # fallback: try last created picking of same origin
            new_pick = self.env["stock.picking"].search([("origin", "=", picking.name)], order="id desc", limit=1)
        if not new_pick:
            raise UserError(_("Could not create reverse picking."))
        return new_pick
