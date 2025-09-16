{
    "name": "Trakka Ops Shell",
    "summary": "Trakka app shell, security groups, base menus, dashboards",
    "version": "17.0.1.0.0",
    "category": "Operations",
    "author": "Trakka",
    "license": "LGPL-3",
    "depends": ["base", "mail", "sale_management", "stock", "account"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/app_menus.xml",
        "views/dashboard_placeholder.xml",
    ],
    "installable": True,
    "application": True,
}
