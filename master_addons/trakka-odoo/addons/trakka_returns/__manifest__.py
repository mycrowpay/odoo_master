{
    "name": "Trakka Returns OS",
    "version": "17.0.1.0.0",
    "depends": [
        "sale",
        "stock",
        "account",
        "mail",
        "trakka_finops",  # ✅ dependency, not a data file
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "data/policy_presets.xml",
        "views/returns_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": True,
}
