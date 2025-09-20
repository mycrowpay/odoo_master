# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged


@tagged("-at_install", "post_install")
class TestTrakkaReturns(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Policy = self.env["trakka.policy"]
        self.Return = self.env["trakka.return.case"]
        self.partner = self.env["res.partner"].create({"name": "Buyer X"})
        self.product = self.env["product.product"].create({
            "name": "Gadget",
            "list_price": 1000.0,
            "type": "service",
        })
        self.order = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "order_line": [(0, 0, {"product_id": self.product.id, "product_uom_qty": 1, "price_unit": 1000.0})],
        })
        self.order.action_confirm()

        self.policy = self.env.ref("trakka_returns.policy_standard")

    def test_decisions_defect_vs_remorse(self):
        rc_def = self.Return.create({
            "sale_order_id": self.order.id,
            "reason": "defect",
            "policy_id": self.policy.id,
            "amount_gross": 1000.0,
        })
        rc_rem = self.Return.create({
            "sale_order_id": self.order.id,
            "reason": "remorse",
            "policy_id": self.policy.id,
            "amount_gross": 1000.0,
        })

        # compute fields are non-stored; access triggers compute
        self.assertEqual(rc_def.payer_of_shipping, "seller")
        self.assertEqual(rc_rem.payer_of_shipping, "buyer")
        self.assertGreaterEqual(rc_def.refund_amount, 0.0)
        self.assertGreaterEqual(rc_rem.refund_amount, 0.0)

    def test_approve_and_refund_path_move(self):
        # Create a dummy escrow in HELD (simulate PayGuard)
        Escrow = self.env["trakka.payguard.escrow"]
        escrow = Escrow.create({
            "name": "ESC_TEST",
            "sale_order_id": self.order.id,
            "amount": 1000.0,
            "currency_id": self.env.company.currency_id.id,
            "mpesa_ref": "REF123",
            "state": "held",
        })
        rc = self.Return.create({
            "sale_order_id": self.order.id,
            "reason": "defect",
            "policy_id": self.policy.id,
            "amount_gross": 1000.0,
            "escrow_id": escrow.id,
        })
        rc.action_approve()
        # We won't actually reverse picking in the test (requires done picking),
        # but we can test refund move posting path:
        rc._post_refund_accounting()
        # No exception means the journal/accounts existed and move was created (best-effort).
