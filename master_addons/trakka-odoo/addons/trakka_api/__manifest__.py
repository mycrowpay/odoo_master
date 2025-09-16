{
    "name": "Trakka Private API",
    "summary": "Private JSON controllers for Gateway/BFF",
    "version": "17.0.1.0.0",
    "category": "Technical",
    "author": "Trakka",
    "license": "LGPL-3",
    "depends": ["trakka_ops", "trakka_finops", "trakka_returns", "trakka_pulse"],
    "external_dependencies": {"python": ["jwt"]},
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
}
