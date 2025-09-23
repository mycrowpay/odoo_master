# -*- coding: utf-8 -*-
{
    "name": "Trakka",
    "summary": "Trakka suite (FinOps + Logi) — escrow, wallet, pricing, dispatch, riders",
    "version": "17.0.1.0.0",
    "category": "Operations/Trakka",
    "author": "Your Company",
    "website": "https://trakka.africa",
    "license": "LGPL-3",
    "depends": ["base", "mail", "sale", "account"],
    "data": [
        # Security
        "security/trakka_groups.xml",
        "security/ir.model.access.csv",
        "security/trakka_rules.xml",
        # Data
        "data/sequences.xml",
        "data/accounts_journals.xml",
        "data/cron.xml",
        # Views (menus first, then each model)
        "views/menu.xml",
        "views/finops_escrow_views.xml",
        "views/wallet_views.xml",
        "views/settlement_batch_views.xml",
        "views/pricing_rule_views.xml",
        "views/dispatch_views.xml",
        "views/rider_views.xml",
        "views/sale_extend_views.xml",
        'views/settings.xml', 
        "views/delivery_connector_views.xml"

    ],
    "application": True,
    "installable": True,
    "auto_install": False,
}
