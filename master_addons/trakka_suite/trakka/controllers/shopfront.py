

from odoo import http, _
from odoo.http import request
import json
import logging
_logger = logging.getLogger(__name__)

def _ok(data): return {"ok": True, **data}
def _err(msg): return {"ok": False, "error": msg}
def _json(data, status=200): return request.make_json_response(data, status=status)

# --- NEW: small helpers -------------------------------------------------------
def _parse_payload():
    """Uniformly parse both GET querystring and POST body JSON."""
    if request.httprequest.method == "GET":
        params = request.params or {}
    else:
        try:
            params = json.loads(request.httprequest.data or b"{}") or {}
        except Exception:
            params = {}
    return params

def _looks_like_company(partner):
    """Seller must be a company partner (works across versions/flags)."""
    return bool(partner and partner.exists() and (
        getattr(partner, "is_company", False) or getattr(partner, "company_type", "") == "company"
    ))

# --- NEW: rock-solid resolver -------------------------------------------------
def _resolve_seller():
    """
    Resolution order:
      1) seller_id (explicit)
      2) seller_slug / seller (explicit)
      3) ICP trakka.shopfront.default_seller_id  (must be a numeric string)
      4) current user's company partner
      5) base.main_company partner
    Returns a recordset( res.partner ) or empty recordset.
    Logs each step.
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
    raw = icp.get_param("trakka.shopfront.default_seller_id", "").strip()
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

# --- keep your controller class but call _resolve_seller() --------------------
class TrakkaShopfrontApi(http.Controller):

    @http.route("/api/v1/shopfront/config", type="http", auth="public", methods=["GET","POST"], csrf=False)
    def config(self, **kwargs):
        seller = _resolve_seller()
        if not seller:
            return _json(_err("seller_not_found"), 404)
        theme = {"logo":"", "primary":"#0ea5e9", "accent":"#f97316", "hero":"Sell better with Trakka."}
        return _json(_ok({"seller":{
            "id": seller.id, "name": seller.display_name, "slug": seller.shop_slug or ""
        }, "theme": theme}))

    @http.route("/api/v1/shopfront/catalog", type="http", auth="public", methods=["GET","POST"], csrf=False)
    def catalog(self, **kwargs):
        # soft-validate seller (keeps contract but never blocks catalog)
        _ = _resolve_seller()
        params = _parse_payload()
        q = (params.get("q") or "").strip()

        Product = request.env["product.product"].sudo()
        domain = [("detailed_type","=","product"), ("sale_ok","=",True), ("shop_publish","=",True)]
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

    @http.route("/api/v1/shopfront/checkout", type="http", auth="public", methods=["POST"], csrf=False)
    def checkout(self, **kwargs):
        params = _parse_payload()
        seller = _resolve_seller()
        if not seller:
            return _json(_err("seller_not_found"), 404)

        lines = params.get("lines") or []
        customer = params.get("customer") or {}
        if not lines:
            return _json(_err("missing_params"), 400)

        partner = request.env["res.partner"].sudo().create({
            "name": customer.get("name") or "Guest",
            "phone": customer.get("phone") or "",
            "mobile": customer.get("phone") or "",
            "type": "contact",
        })
        Product = request.env["product.product"].sudo()
        so_lines = []
        for l in lines:
            p = Product.browse(int(l["product_id"]))
            so_lines.append((0,0,{"product_id": p.id, "product_uom_qty": float(l.get("qty") or 1.0)}))

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

    @http.route("/api/v1/shopfront/checkout/pay", type="http", auth="public", methods=["POST"], csrf=False)
    def checkout_pay(self, **kwargs):
        params = _parse_payload()
        so_id = int(params.get("so_id") or 0)
        phone = (params.get("phone") or "").strip()
        if not so_id or not phone:
            return _json(_err("missing_params"), 400)
        so = request.env["sale.order"].sudo().browse(so_id)
        if not so.exists():
            return _json(_err("so_not_found"), 404)
        intent = request.env["trakka.mpesa.intent"].sudo().create_for_checkout(so, phone)
        intent.sudo().action_stk_push()
        return _json(_ok({"psp_ref": intent.psp_ref}))
