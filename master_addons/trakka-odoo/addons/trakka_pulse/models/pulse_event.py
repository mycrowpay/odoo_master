from odoo import fields, models

class TrakkaPulseEvent(models.Model):
    _name = "trakka.pulse.event"
    _description = "Delivery telemetry events"

    rider_id = fields.Many2one("trakka.pulse.rider", required=True)
    sale_order_id = fields.Many2one("sale.order")
    picking_id = fields.Many2one("stock.picking")
    event_type = fields.Selection([
        ("pop_verified","PoP Verified"),
        ("on_time","On Time"),
        ("no_show","No Show"),
        ("gps_sample","GPS Sample"),
    ], required=True)
    event_ref = fields.Char()
    event_ts = fields.Datetime(default=fields.Datetime.now)
