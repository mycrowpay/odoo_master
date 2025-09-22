from odoo import api, SUPERUSER_ID

def post_init_create_journals(cr, registry):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for company in env["res.company"].search([]):
        for code, name in [("ESC", "Escrow"), ("WLT", "Wallet")]:
            j = env["account.journal"].with_company(company).search([("code", "=", code)], limit=1)
            if not j:
                env["account.journal"].with_company(company).create({
                    "name": name,
                    "code": code,
                    "type": "general",
                    "company_id": company.id,
                })
