# master_addons/trakka_suite/trakka/controllers/shopfront.py
# -*- coding: utf-8 -*-
from odoo import http, _
from odoo.http import request
import json

def _json(data, status=200):
    # Always return well-formed JSON responses for http routes
    return request.make_json_response(data, status=status)

def _ok(data=None):
    return _json({"ok": True, **(data or {})})

def _err(msg, status=400, **extra):
    return _json({"ok": False, "error": msg, **extra}, status=status)

class TrakkaShopfrontApi(http.Controller):

    @http.route("/api/v1/shopfront/config", type="http", auth="public", methods=["GET", "POST"], csrf=False)
    def config(self, **kwargs):
        if request.httprequest.method == "GET":
            slug = (request.params.get("seller") or "").strip()
        else:
            try:
                payload = json.loads(request.httprequest.data or b"{}")
            except Exception:
                payload = {}
            slug = (payload.get("seller") or "").strip()

        if not slug:
            return _err("missing_seller")
        seller = request.env["res.partner"].sudo().search([("shop_slug", "=", slug), ("is_company", "=", True)], limit=1)
        if not seller:
            return _err("seller_not_found", status=404)
        theme = {"logo": "", "primary": "#0ea5e9", "accent": "#f97316", "hero": "Sell better with Trakka."}
        return _ok({"seller": {"id": seller.id, "name": seller.display_name, "slug": slug}, "theme": theme})

    @http.route("/api/v1/shopfront/catalog", type="http", auth="public", methods=["GET", "POST"], csrf=False)
    def catalog(self, **kwargs):
        if request.httprequest.method == "GET":
            slug = (request.params.get("seller") or "").strip()
            q = (request.params.get("q") or "").strip()
        else:
            try:
                payload = json.loads(request.httprequest.data or b"{}")
            except Exception:
                payload = {}
            slug = (payload.get("seller") or "").strip()
            q = (payload.get("q") or "").strip()

        if not slug:
            return _err("missing_seller")

        Product = request.env["product.product"].sudo()
        domain = [("detailed_type", "=", "product"), ("sale_ok", "=", True), ("shop_publish", "=", True)]
        if q:
            domain = ["|", ("name", "ilike", q), ("default_code", "ilike", q)] + domain

        products = Product.search(domain, limit=60)
        items = [{
            "id": p.id,
            "name": p.display_name,
            "price": p.lst_price,
            "currency": (p.currency_id and p.currency_id.name) or (p.company_id.currency_id.name),
            "image_128": p.image_128 and f"/web/image/product.product/{p.id}/image_128" or "",
            "available": True,
        } for p in products]
        return _ok({"items": items})

    @http.route("/api/v1/shopfront/checkout", type="http", auth="public", methods=["POST"], csrf=False)
    def checkout(self, **kwargs):
        try:
            payload = json.loads(request.httprequest.data or b"{}")
        except Exception:
            payload = {}
        seller_slug = (payload.get("seller_slug") or "").strip()
        lines = payload.get("lines") or []
        customer = payload.get("customer") or {}
        if not seller_slug or not lines:
            return _err("missing_params")

        seller = request.env["res.partner"].sudo().search([("shop_slug", "=", seller_slug)], limit=1)
        if not seller:
            return _err("seller_not_found", status=404)

        partner = request.env["res.partner"].sudo().create({
            "name": customer.get("name") or "Guest",
            "phone": customer.get("phone") or "",
            "mobile": customer.get("phone") or "",
            "type": "contact",
        })

        so_lines, Product = [], request.env["product.product"].sudo()
        for l in lines:
            p = Product.browse(int(l["product_id"]))
            so_lines.append((0, 0, {
                "product_id": p.id,
                "product_uom_qty": float(l.get("qty") or 1.0),
            }))
        so = request.env["sale.order"].sudo().create({
            "partner_id": partner.id,
            "order_line": so_lines,
            "client_order_ref": f"SHOP-{seller_slug}",
        })

        Escrow = request.env["trakka.payguard.escrow"].sudo()
        esc = Escrow.search([("sale_order_id", "=", so.id)], limit=1)
        if not esc:
            esc = Escrow.create({"sale_order_id": so.id, "amount": so.amount_total})

        return _ok({"so_id": so.id, "amount": so.amount_total})

    @http.route("/api/v1/shopfront/checkout/pay", type="http", auth="public", methods=["POST"], csrf=False)
    def checkout_pay(self, **kwargs):
        try:
            payload = json.loads(request.httprequest.data or b"{}")
        except Exception:
            payload = {}
        so_id = int(payload.get("so_id") or 0)
        phone = (payload.get("phone") or "").strip()
        if not so_id or not phone:
            return _err("missing_params")

        so = request.env["sale.order"].sudo().browse(so_id)
        if not so.exists():
            return _err("so_not_found", status=404)

        intent = request.env["trakka.mpesa.intent"].sudo().create_for_checkout(so, phone)
        intent.sudo().action_stk_push()
        return _ok({"psp_ref": intent.psp_ref})
