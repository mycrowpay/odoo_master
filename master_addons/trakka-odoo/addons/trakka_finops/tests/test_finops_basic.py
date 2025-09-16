# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase

class TestFinOpsBasic(TransactionCase):
    def setUp(self):
        super().setUp()
        self.Partner = self.env["res.partner"]
        self.Sale = self.env["sale.order"]
        self.Escrow = self.env["trakka.payguard.escrow"]
        self.Batch = self.env["trakka.settlement.batch"]

        self.partner = self.Partner.create({"name": "Seller A"})
        self.so = self.Sale.create({"partner_id": self.partner.id})

    def test_escrow_release_and_settlement(self):
        esc = self.Escrow.create({
            "name": "ESC-TEST",
            "sale_order_id": self.so.id,
            "amount": 100.0,
            "currency_id": self.env.company.currency_id.id,
        })
        esc.action_mark_released_ready()
        self.assertEqual(esc.state, "released_ready")

        batch_id = self.Batch.cron_nightly_settlement()
        esc.refresh()
        self.assertEqual(esc.state, "released")
        self.assertTrue(esc.settlement_move_id)
        self.assertTrue(esc.wallet_move_id)
