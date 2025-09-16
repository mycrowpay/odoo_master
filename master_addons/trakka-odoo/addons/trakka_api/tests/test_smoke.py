from odoo.tests.common import HttpCase

class TestApiSmoke(HttpCase):
    def test_ping_requires_auth(self):
        # Just a placeholder; full tests in Milestone 5
        self.assertTrue(True)
