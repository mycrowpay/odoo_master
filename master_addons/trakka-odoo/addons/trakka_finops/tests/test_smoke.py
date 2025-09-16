from odoo.tests.common import TransactionCase

class TestFinOpsSmoke(TransactionCase):
    def test_models(self):
        self.env["trakka.payguard.escrow"].create({
            "name": "ESC-TEST",
            "sale_order_id": self.env["sale.order"].create({"partner_id": self.env.ref("base.res_partner_1").id}).id,
            "amount": 0.0,
        })
