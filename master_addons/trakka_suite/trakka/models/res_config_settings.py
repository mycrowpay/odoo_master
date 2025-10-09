# -*- coding: utf-8 -*-
from odoo import fields, models  # <- no api import needed

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # Company-level toggle (unchanged)
    trakka_require_invoice_before_settlement = fields.Boolean(
        related="company_id.trakka_require_invoice_before_settlement",
        readonly=False
    )

    # --- M-Pesa: every field persisted via ir.config_parameter -----------------
    trakka_mpesa_mode = fields.Selection(
        [('dummy', 'Dummy (no live calls)'), ('live', 'Live (Daraja)')],
        string="M-Pesa Mode",
        default='dummy',
        config_parameter='trakka.mpesa.mode',
        help="Dummy avoids network calls and auto-approves flows for testing."
    )
    trakka_mpesa_env = fields.Selection(
        [('sandbox', 'Sandbox'), ('production', 'Production')],
        string="Daraja Environment",
        default='sandbox',
        config_parameter='trakka.mpesa.env',
        help="Used to infer base URL if an explicit Base URL is not provided."
    )
    trakka_mpesa_base_url = fields.Char(
        string="Daraja Base URL",
        config_parameter='trakka.mpesa.base_url',
        help="Optional. Overrides the environment-based default. "
             "Sandbox: https://sandbox.safaricom.co.ke, "
             "Production: https://api.safaricom.co.ke"
    )

    # Credentials
    trakka_mpesa_consumer_key = fields.Char(
        string="Consumer Key",
        config_parameter='trakka.mpesa.consumer_key',
    )
    trakka_mpesa_consumer_secret = fields.Char(
        string="Consumer Secret",
        config_parameter='trakka.mpesa.consumer_secret',
    )

    # LNM / Paybill
    trakka_mpesa_short_code = fields.Char(
        string="Short Code / Paybill/Till",
        config_parameter='trakka.mpesa.short_code',
    )
    trakka_mpesa_passkey = fields.Char(
        string="Lipa Na M-Pesa Passkey",
        config_parameter='trakka.mpesa.passkey',
    )

    # Callback + defaults
    trakka_mpesa_callback_base = fields.Char(
        string="Callback Base URL",
        config_parameter='trakka.mpesa.callback_base',
        help="Your public base (e.g. https://9617-102-0-6-90.ngrok-free.app). "
             "The system appends /webhooks/mpesa."
    )
    trakka_mpesa_account_ref = fields.Char(
        string="Account Reference",
        default="TRAKKA",
        config_parameter='trakka.mpesa.account_ref',
    )
    trakka_mpesa_trans_desc = fields.Char(
        string="Transaction Description",
        default="Order Payment",
        config_parameter='trakka.mpesa.trans_desc',
    )
