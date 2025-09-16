{
    "name": "Trakka Returns OS",
    "summary": "Returns policies and orchestration",
    "version": "17.0.1.0.0",
    "category": "Inventory/Returns",
    "author": "Trakka",
    "license": "LGPL-3",
    "depends": ["trakka_ops", "stock", "account", "sale_management"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/policy_presets.xml",
        "views/menu.xml",
        "views/returns_views.xml",
    ],
    "installable": True,
    "application": False,
}
