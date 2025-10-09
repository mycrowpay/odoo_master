# -*- coding: utf-8 -*-
import base64, datetime, json, logging, requests
from odoo import api

_logger = logging.getLogger(__name__)
DARAJA_TIMEOUT = 20

class DarajaClient(object):
    def __init__(self, env):
        ICP = env['ir.config_parameter'].sudo()
        self.mode = (ICP.get_param('trakka.mpesa.mode') or 'dummy').strip().lower()
        env_name = (ICP.get_param('trakka.mpesa.env') or 'sandbox').strip().lower()

        # Read explicit base_url but validate it must start with http
        base_url = (ICP.get_param('trakka.mpesa.base_url') or '').strip()
        if base_url and not base_url.lower().startswith(('http://', 'https://')):
            _logger.warning(
                "Invalid trakka.mpesa.base_url=%r; falling back to environment=%s",
                base_url, env_name
            )
            base_url = ''
        if not base_url:
            base_url = 'https://sandbox.safaricom.co.ke' if env_name == 'sandbox' else 'https://api.safaricom.co.ke'
        self.base_url = base_url.rstrip('/')

        self.ck = (ICP.get_param('trakka.mpesa.consumer_key') or '').strip()
        self.cs = (ICP.get_param('trakka.mpesa.consumer_secret') or '').strip()
        self.short_code = (ICP.get_param('trakka.mpesa.short_code') or '').strip()
        self.passkey = (ICP.get_param('trakka.mpesa.passkey') or '').strip()

        callback_base = (ICP.get_param('trakka.mpesa.callback_base') or '').strip().rstrip('/')
        self.callback_url = f"{callback_base}/webhooks/mpesa" if callback_base else ''
        self.account_ref = (ICP.get_param('trakka.mpesa.account_ref') or 'TRAKKA').strip()
        self.trans_desc = (ICP.get_param('trakka.mpesa.trans_desc') or 'Order Payment').strip()

    def _now_ts(self):
        dt = datetime.datetime.utcnow() + datetime.timedelta(hours=3)  # EAT offset
        return dt.strftime('%Y%m%d%H%M%S')

    def _password(self, ts):
        raw = f"{self.short_code}{self.passkey}{ts}".encode('utf-8')
        return base64.b64encode(raw).decode('utf-8')

    def _normalize_msisdn(self, msisdn):
        s = ''.join(ch for ch in str(msisdn) if ch.isdigit())
        if s.startswith('07'):      # e.g. 0712...
            s = '254' + s[1:]
        elif s.startswith('7'):     # e.g. 712...
            s = '254' + s
        if not s.startswith('254'):
            raise ValueError("MSISDN must be in 2547XXXXXXXX format")
        return s

    def _oauth_token(self):
        url = f"{self.base_url}/oauth/v1/generate?grant_type=client_credentials"
        resp = requests.get(url, auth=(self.ck, self.cs), timeout=DARAJA_TIMEOUT)
        resp.raise_for_status()
        return resp.json().get('access_token')

    def stk_push(self, amount, msisdn, account_ref=None, trans_desc=None, psp_ref_hint=None):
        if self.mode == 'dummy':
            rid = f"DUMMY-{psp_ref_hint or 'NA'}"
            payload = {"mode": "dummy", "CheckoutRequestID": rid, "MerchantRequestID": rid}
            return {"ok": True, "payload": payload, "psp_ref": rid, "error": None}

        # Normalize MSISDN
        try:
            msisdn_norm = self._normalize_msisdn(msisdn)
        except ValueError as e:
            return {"ok": False, "payload": {}, "psp_ref": None, "error": str(e)}

        # Explicit missing list
        missing = []
        if not self.ck: missing.append("consumer_key")
        if not self.cs: missing.append("consumer_secret")
        if not self.short_code: missing.append("short_code")
        if not self.passkey: missing.append("passkey")
        if not self.callback_url: missing.append("callback_base")
        if missing:
            return {
                "ok": False,
                "payload": {},
                "psp_ref": None,
                "error": f"Missing M-Pesa configuration: {', '.join(missing)}",
            }

        token = self._oauth_token()
        ts = self._now_ts()
        payload = {
            "BusinessShortCode": self.short_code,
            "Password": self._password(ts),
            "Timestamp": ts,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": int(round(float(amount))),
            "PartyA": msisdn_norm,
            "PartyB": self.short_code,
            "PhoneNumber": msisdn_norm,
            "CallBackURL": self.callback_url,
            "AccountReference": account_ref or self.account_ref,
            "TransactionDesc": trans_desc or self.trans_desc,
        }
        url = f"{self.base_url}/mpesa/stkpush/v1/processrequest"
        headers = {"Authorization": f"Bearer {token}"}
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=DARAJA_TIMEOUT)
            try:
                j = resp.json()
            except Exception:
                j = {}
            if resp.status_code == 200 and j.get('ResponseCode') == '0':
                psp_ref = j.get('CheckoutRequestID') or j.get('MerchantRequestID')
                return {"ok": True, "payload": j, "psp_ref": psp_ref, "error": None}
            return {"ok": False, "payload": j, "psp_ref": None,
                    "error": j.get('errorMessage') or j.get('error') or resp.text}
        except requests.RequestException as e:
            _logger.exception("Daraja STK error: %s", e)
            return {"ok": False, "payload": {}, "psp_ref": None, "error": str(e)}

def daraja(env):
    return DarajaClient(env)
