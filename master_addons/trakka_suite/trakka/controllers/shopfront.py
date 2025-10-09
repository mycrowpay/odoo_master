# -*- coding: utf-8 -*-
from odoo import http, _
from odoo.http import request
import json
import logging
_logger = logging.getLogger(__name__)

def _ok(data): return {"ok": True, **data}
def _err(msg, **extra): 
    d = {"ok": False, "error": msg}
    if extra: d.update(extra)
    return d
def _json(data, status=200):
    resp = request.make_json_response(data, status=status)
    # CORS headers for safety (even though cors="*" is set)
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Vary'] = 'Origin'
    return resp

# --- helpers -----------------------------------------------------------------
def _parse_payload():
    """Uniformly parse both GET querystring and POST body JSON."""
    if request.httprequest.method == "GET":
        params = request.params or {}
    else:
        try:
            raw = request.httprequest.data or b"{}"
            params = json.loads(raw) or {}
        except Exception:
            params = {}
    return params

def _looks_like_company(partner):
    """Seller must be a company partner (works across versions/flags)."""
    return bool(partner and partner.exists() and (
        getattr(partner, "is_company", False) or getattr(partner, "company_type", "") == "company"
    ))

def _resolve_seller():
    """
    Resolution order:
      1) seller_id (explicit)
      2) seller_slug / seller (explicit)
      3) ICP trakka.shopfront.default_seller_id  (must be a numeric string)
      4) current user's company partner
      5) base.main_company partner
    """
    params = _parse_payload()
    slug = (params.get("seller_slug") or params.get("seller") or "").strip()
    seller_id = 0
    try:
        seller_id = int(params.get("seller_id") or 0)
    except Exception:
        seller_id = 0

    Seller = request.env["res.partner"].sudo()

    # 1) Explicit seller_id
    if seller_id:
        s = Seller.browse(seller_id)
        if _looks_like_company(s):
            _logger.info("shopfront: resolved seller via seller_id=%s", s.id)
            return s
        _logger.warning("shopfront: seller_id=%s not a company or not found", seller_id)

    # 2) Explicit slug
    if slug:
        s = Seller.search([("shop_slug", "=", slug)], limit=1)
        if _looks_like_company(s):
            _logger.info("shopfront: resolved seller via slug=%s -> id=%s", slug, s.id)
            return s
        _logger.warning("shopfront: slug=%s not found or not a company", slug)

    # 3) ICP param
    icp = request.env["ir.config_parameter"].sudo()
    raw = (icp.get_param("trakka.shopfront.default_seller_id", "") or "").strip()
    if raw:
        try:
            default_id = int(raw)
        except Exception:
            default_id = 0
            _logger.warning("shopfront: ICP default_seller_id is not numeric: %r", raw)
        if default_id:
            s = Seller.browse(default_id)
            if _looks_like_company(s):
                _logger.info("shopfront: resolved seller via ICP default id=%s", s.id)
                return s
            _logger.warning("shopfront: ICP default id=%s not found / not a company", default_id)

    # 4) Current user's company partner
    cu = request.env.user
    if cu and cu.company_id and cu.company_id.partner_id:
        s = cu.company_id.partner_id.sudo()
        if _looks_like_company(s):
            _logger.info("shopfront: resolved seller via current user's company partner id=%s", s.id)
            return s

    # 5) Base main company partner
    try:
        base_company = request.env.ref("base.main_company")
        if base_company and base_company.partner_id:
            s = base_company.partner_id.sudo()
            if _looks_like_company(s):
                _logger.info("shopfront: resolved seller via base.main_company partner id=%s", s.id)
                return s
    except Exception as e:
        _logger.exception("shopfront: failed resolving base.main_company: %s", e)

    _logger.error("shopfront: could not resolve seller (no id/slug/default/company fallback)")
    return Seller.browse()  # empty

class TrakkaShopfrontApi(http.Controller):

    # ---------------------- CORS preflight (one handler for many) --------------
    @http.route([
        "/api/v1/shopfront/config",
        "/api/v1/shopfront/catalog",
        "/api/v1/shopfront/checkout",
        "/api/v1/shopfront/checkout/pay",
        "/payments/mpesa/stk/init",
        "/webhooks/mpesa",
    ], type="http", auth="public", methods=["OPTIONS"], csrf=False, cors="*")
    def preflight(self, **kwargs):
        resp = request.make_response('', headers=[
            ('Access-Control-Allow-Origin', '*'),
            ('Access-Control-Allow-Methods', 'GET, POST, OPTIONS'),
            ('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Requested-With'),
            ('Access-Control-Max-Age', '86400'),
        ])
        return resp

    @http.route("/api/v1/shopfront/config", type="http", auth="public", methods=["GET","POST"], csrf=False, cors="*")
    def config(self, **kwargs):
        seller = _resolve_seller()
        if not seller:
            return _json(_err("seller_not_found"), 404)
        derived_slug = seller.shop_slug or f"company-{seller.id}"

        theme = {"logo":"", "primary":"#0ea5e9", "accent":"#f97316", "hero":"Sell better with Trakka."}
        return _json(_ok({
            "seller": {
                "id": seller.id,
                "name": seller.display_name,
                "slug": derived_slug,
            },
            "theme": theme
        }))

    @http.route("/api/v1/shopfront/catalog", type="http", auth="public", methods=["GET","POST"], csrf=False, cors="*")
    def catalog(self, **kwargs):
        # soft-validate seller (keeps contract but never blocks catalog)
        _ = _resolve_seller()
        params = _parse_payload()
        q = (params.get("q") or "").strip()

        Product = request.env["product.product"].sudo()
        domain = [("detailed_type","=","product"), ("sale_ok","=",True)]
        # Your field 'shop_publish'—fallback to website_published if needed
        if 'shop_publish' in Product._fields:
            domain.append(("shop_publish","=",True))
        else:
            domain.append(("product_tmpl_id.website_published","=",True))
        if q:
            domain += ["|", ("name","ilike",q), ("default_code","ilike",q)]
        products = Product.search(domain, limit=60)
        items = [{
            "id": p.id,
            "name": p.display_name,
            "price": p.lst_price,
            "currency": p.currency_id.name,
            "image_128": p.image_128 and f"/web/image/product.product/{p.id}/image_128" or "",
            "available": True,
        } for p in products]
        return _json(_ok({"items": items}))

    @http.route("/api/v1/shopfront/checkout", type="http", auth="public", methods=["POST"], csrf=False, cors="*")
    def checkout(self, **kwargs):
        params = _parse_payload()
        seller = _resolve_seller()
        if not seller:
            return _json(_err("seller_not_found"), 404)

        lines = params.get("lines") or []
        customer = params.get("customer") or {}
        if not lines:
            return _json(_err("no_lines"), 400)

        # Create a simple guest partner for this order
        partner = request.env["res.partner"].sudo().create({
            "name": customer.get("name") or "Guest",
            "phone": customer.get("phone") or "",
            "mobile": customer.get("phone") or "",
            "type": "contact",
        })

        Product = request.env["product.product"].sudo()
        so_lines = []

        for l in lines:
            try:
                pid = int(l.get("product_id"))
            except Exception:
                return _json(_err("invalid_product", detail=l), 400)
            try:
                qty = float(l.get("qty") or 1.0)
            except Exception:
                return _json(_err("invalid_qty", detail=l), 400)
            if qty <= 0:
                return _json(_err("invalid_qty", detail=l), 400)

            p = Product.browse(pid)
            if not p.exists() or not p.sale_ok:
                return _json(_err("product_not_sellable", product_id=pid), 400)
            if 'shop_publish' in Product._fields:
                if not p.shop_publish:
                    return _json(_err("product_not_published", product_id=pid), 400)
            else:
                if not p.product_tmpl_id.website_published:
                    return _json(_err("product_not_published", product_id=pid), 400)

            so_lines.append((0,0,{
                "product_id": p.id,
                "product_uom_qty": qty,
                "price_unit": p.lst_price,
                "name": p.name,
            }))

        so = request.env["sale.order"].sudo().create({
            "partner_id": partner.id,
            "order_line": so_lines,
            "client_order_ref": f"SHOP-{seller.id}",
            "company_id": request.env.user.company_id.id,
        })

        Escrow = request.env["trakka.payguard.escrow"].sudo()
        esc = Escrow.search([("sale_order_id","=",so.id)], limit=1) or \
              Escrow.create({"sale_order_id": so.id, "amount": so.amount_total})

        return _json(_ok({"so_id": so.id, "amount": so.amount_total}))

    @http.route("/api/v1/shopfront/checkout/pay", type="http", auth="public", methods=["POST"], csrf=False, cors="*")
    def checkout_pay(self, **kwargs):
        params = _parse_payload()
        try:
            so_id = int(params.get("so_id") or 0)
        except Exception:
            so_id = 0
        phone = (params.get("phone") or "").strip()
        if not so_id or not phone:
            return _json(_err("missing_params"), 400)

        so = request.env["sale.order"].sudo().browse(so_id)
        if not so.exists():
            return _json(_err("so_not_found"), 404)

        intent = request.env["trakka.mpesa.intent"].sudo().create_for_checkout(so, phone)
        res = intent.sudo().action_stk_push()
        # res is a dict from action_stk_push()
        return _json(_ok({
            "psp_ref": res.get("psp_ref"),
            "state": res.get("state"),
            "error": res.get("error"),
        }))
