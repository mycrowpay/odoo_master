from odoo.tests.common import TransactionCase

class TestReturnsSmoke(TransactionCase):
    def test_policy_preset_loaded(self):
        self.env.ref("trakka_returns.policy_standard")
