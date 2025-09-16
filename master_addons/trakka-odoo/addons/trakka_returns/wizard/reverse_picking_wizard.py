# -*- coding: utf-8 -*-
from odoo import fields, models

class ReversePickingWizard(models.TransientModel):
    _name = "trakka.reverse.picking.wizard"
    _description = "Reverse Picking Wizard"

    picking_id = fields.Many2one("stock.picking", required=True)
