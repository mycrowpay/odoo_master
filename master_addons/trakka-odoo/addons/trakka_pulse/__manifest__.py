{
    "name": "Trakka Pulse",
    "summary": "Rider & delivery telemetry (read-mostly)",
    "version": "17.0.1.0.0",
    "category": "Operations",
    "author": "Trakka",
    "license": "LGPL-3",
    "depends": ["trakka_ops", "stock", "sale_management"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/menu.xml",
        "views/pulse_views.xml",
    ],
    "installable": True,
    "application": False,
}
