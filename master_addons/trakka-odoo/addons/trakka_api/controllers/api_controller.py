# addons/trakka_api/controllers/api_controller.py
# -*- coding: utf-8 -*-
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

def _get_param(key, default=None):
    """Fetch from System Parameters, fallback to env var."""
    ICP = request.env["ir.config_parameter"].sudo()
    return ICP.get_param(key) or ICP.get_param(key.upper()) or default

def _require_bearer_and_idem(req):
    """Validate Bearer JWT + Idempotency-Key. Lazy-import PyJWT."""
    auth = (req.httprequest.headers.get("Authorization") or "").strip()
    idem = req.httprequest.headers.get("Idempotency-Key")
    if not auth.startswith("Bearer ") or not idem:
        _logger.debug("Missing/invalid Authorization header or Idempotency-Key")
        return None, None

    try:
        import jwt  # lazy import so module loads even if PyJWT is missing
    except Exception as e:
        _logger.error("PyJWT not installed. pip install PyJWT. Error: %s", e)
        return None, None

    token = auth.split(" ", 1)[1]
    secret = _get_param("trakka_api.jwt_secret")
    if not secret:
        _logger.error("Missing JWT secret (set system param trakka_api.jwt_secret).")
        return None, None

    audience = _get_param("trakka_api.jwt_aud", "trakka-gateway")
    issuer = _get_param("trakka_api.jwt_iss", "trakka-core")

    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=audience,
            issuer=issuer,
        )
        return payload, idem
    except jwt.ExpiredSignatureError:
        _logger.info("JWT expired")
    except jwt.InvalidTokenError as e:
        _logger.warning("Invalid JWT: %s", e)
    except Exception as e:
        _logger.warning("JWT decode failed: %s", e)

    return None, None

class TrakkaApiController(http.Controller):

    @http.route("/api/ping", type="json", auth="none", csrf=False, methods=["POST"])
    def ping(self, **kwargs):
        payload, idem = _require_bearer_and_idem(request)
        if not payload:
            # For type="json", return a JSON error (status code will be 200 in dev)
            return {"ok": False, "error": "unauthorized"}
        return {"ok": True, "idem": idem}
