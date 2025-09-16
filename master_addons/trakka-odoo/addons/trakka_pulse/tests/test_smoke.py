from odoo.tests.common import TransactionCase

class TestPulseSmoke(TransactionCase):
    def test_models_exist(self):
        self.env["trakka.pulse.rider"].create({"name": "Rider X"})
