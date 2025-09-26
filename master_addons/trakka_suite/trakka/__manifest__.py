# -*- coding: utf-8 -*-
{
    "name": "Trakka",
    "summary": "Trakka suite (FinOps + Logistics) — escrow, wallet, pricing, dispatch, riders",
    "version": "17.0.1.0.0",
    "category": "Operations/Trakka",
    "author": "Your Company",
    "website": "https://trakka.africa",
    "license": "LGPL-3",

    # Deps needed by your models:
    # - mail: you inherit mail.thread
    # - stock: you use stock.picking
    # - sale_management: Sales app (sale.order)
    # - sale_stock: link sale <-> picking (provides picking.sale_id)
    # - account: invoicing bits
    "depends": ["base", "mail", "stock", "sale_management", "sale_stock", "account"],

    "data": [
        # --- Security ---
        "security/trakka_groups.xml",
        "security/ir.model.access.csv",
        "security/trakka_rules.xml",

        # --- Data ---
        "data/sequences.xml",
        "data/accounts_journals.xml",
        "data/cron.xml",
        "data/demo_connectors.xml",

        # --- Views & Actions (ACTION BEFORE MENU!) ---
        "views/dispatch_views.xml",          # defines action_trakka_dispatch_orders
        "views/menu.xml",                    # uses that action

        "views/finops_escrow_views.xml",
        "views/wallet_views.xml",
        "views/settlement_batch_views.xml",
        "views/pricing_rule_views.xml",
        "views/rider_views.xml",
        "views/sale_extend_views.xml",
        "views/settings.xml",
        "views/delivery_connector_views.xml",
    ],

    "application": True,
    "installable": True,
    "auto_install": False,
}
