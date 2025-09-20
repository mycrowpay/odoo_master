# -*- coding: utf-8 -*-
{
    "name": "Trakka FinOps",
    "summary": "Escrow, Wallet, Settlements for Trakka",
    "version": "17.0.2.0.0",
    "category": "Accounting",
    "author": "Trakka",
    "license": "LGPL-3",
    "depends": ["trakka_ops", "account", "sale_management","sales_team", "stock"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/accounts_journals.xml",
        "data/sequences.xml",
        "data/cron.xml",                 
        "views/menu.xml",
        "views/finops_views.xml",
    ],
    "external_dependencies": {
        "python": []
    },
    "installable": True,
    "application": False,
}
