from odoo.tests.common import TransactionCase

class TestOpsSmoke(TransactionCase):
    def test_groups_exist(self):
        for xmlid in [
            "trakka_ops.trakka_group_admin",
            "trakka_ops.trakka_group_finance",
            "trakka_ops.trakka_group_ops",
            "trakka_ops.trakka_group_support",
            "trakka_ops.trakka_group_readonly",
        ]:
            self.env.ref(xmlid)
