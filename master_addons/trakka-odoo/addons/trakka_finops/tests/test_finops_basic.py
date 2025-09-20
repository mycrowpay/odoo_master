# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class TestFinOps(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Partner = self.env["res.partner"]
        self.Sale = self.env["sale.order"]
        self.Escrow = self.env["trakka.payguard.escrow"]
        self.Batch = self.env["trakka.settlement.batch"]

        self.partner = self.Partner.create({"name": "Test Buyer"})
        self.so = self.Sale.create({
            "partner_id": self.partner.id,
            "order_line": [],
        })

    def test_escrow_flow_and_settlement(self):
        esc = self.Escrow.create({
            "sale_order_id": self.so.id,
            "amount": 100.0,
            "currency_id": self.env.company.currency_id.id,
            "mpesa_ref": "REF123",
        })
        self.assertEqual(esc.state, "held")

        esc.action_mark_released_ready()
        self.assertEqual(esc.state, "released_ready")

        # run cron
        self.Batch._cron_settle_released_ready()

        esc.refresh()
        self.assertEqual(esc.state, "released")
        self.assertTrue(esc.wallet_move_id, "Wallet move not created")
        self.assertTrue(esc.settlement_move_id, "Account move not created")
