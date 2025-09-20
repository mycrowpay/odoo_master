# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
import json


class TrakkaReturnCase(models.Model):
    _name = "trakka.return.case"
    _description = "Trakka Return Case"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = "id desc"

    # ----------------------------------------------------------------------------------
    # Fields
    # ----------------------------------------------------------------------------------
    name = fields.Char(default=lambda self: _("New"), readonly=True, copy=False, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('approved', 'Approved'),
        ('reversed', 'Reversed'),     # stock reversed and/or credit prepared
        ('refunded', 'Refunded'),     # credit note posted
        ('cancelled', 'Cancelled'),
    ], default='draft', tracking=True)

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)

    sale_order_id = fields.Many2one('sale.order', string="Sale Order", tracking=True, index=True)
    partner_id = fields.Many2one('res.partner', string="Customer", tracking=True, compute="_compute_partner", store=True, readonly=False)
    picking_id = fields.Many2one('stock.picking', string="Delivery Picking", tracking=True)
    invoice_id = fields.Many2one('account.move', string="Customer Invoice", domain=[('move_type', '=', 'out_invoice')], tracking=True)
    escrow_id = fields.Many2one('trakka.payguard.escrow', string="Escrow", tracking=True)

    policy_id = fields.Many2one('trakka.policy', string="Policy", required=True, tracking=True)
    reason = fields.Selection(
    [
        ('defect', 'Defect'),
        ('remorse', 'Buyer Remorse'),
        ('other', 'Other'),
    ],
    string="Reason",
    tracking=True,
)


    currency_id = fields.Many2one('res.currency', required=True, default=lambda self: self.env.company.currency_id, tracking=True)
    subtotal_amount = fields.Monetary(string="Subtotal", currency_field='currency_id', compute="_compute_subtotal", store=True, readonly=True)

    # Effective override flag (comes from policy and/or category overrides; keep simple: mirror policy)
    allow_overrides_effective = fields.Boolean(string="Overrides Allowed (Effective)", compute="_compute_allow_overrides_effective", store=True, readonly=True)

    # System-computed fee/refund (when overrides not allowed)
    fee_amount = fields.Monetary(string="Fee Amount", currency_field='currency_id', compute="_compute_fee_and_refund", store=True, readonly=True)
    refund_amount = fields.Monetary(string="Refund Amount", currency_field='currency_id', compute="_compute_fee_and_refund", store=True, readonly=True)

    # Manual overrides (used only if allow_overrides_effective = True)
    fee_override = fields.Monetary(string="Fee (Override)", currency_field='currency_id')
    refund_override = fields.Monetary(string="Refund (Override)", currency_field='currency_id')

    reverse_picking_id = fields.Many2one('stock.picking', string="Return Picking", readonly=True)
    refund_move_id = fields.Many2one('account.move', string="Credit Note", readonly=True, domain=[('move_type', '=', 'out_refund')])

    approved_by = fields.Many2one('res.users', string="Approved By", readonly=True)
    approved_on = fields.Datetime(string="Approved On", readonly=True)
    policy_snapshot = fields.Text(string="Policy Snapshot", readonly=True)

    # ----------------------------------------------------------------------------------
    # Onchanges / Computes
    # ----------------------------------------------------------------------------------
    @api.depends('sale_order_id', 'invoice_id')
    def _compute_partner(self):
        for rec in self:
            partner = rec.partner_id
            if rec.sale_order_id:
                partner = rec.sale_order_id.partner_id
            if rec.invoice_id:
                partner = rec.invoice_id.partner_id
            rec.partner_id = partner

    @api.depends('invoice_id', 'sale_order_id', 'currency_id')
    def _compute_subtotal(self):
        """Minimal subtotal heuristic:
        - Prefer invoice total if present
        - Else SO total
        - Else 0
        """
        for rec in self:
            subtotal = 0.0
            if rec.invoice_id:
                # amount_total is in invoice currency; monetary field will render with rec.currency_id
                subtotal = rec.invoice_id.amount_total
            elif rec.sale_order_id:
                subtotal = rec.sale_order_id.amount_total
            rec.subtotal_amount = subtotal

    @api.depends('policy_id.allow_overrides')
    def _compute_allow_overrides_effective(self):
        # Keep it simple for M3: mirror policy setting
        for rec in self:
            rec.allow_overrides_effective = bool(rec.policy_id and rec.policy_id.allow_overrides)

    @api.depends('policy_id.fee_type', 'policy_id.fee_value', 'subtotal_amount',
                 'allow_overrides_effective', 'fee_override', 'refund_override')
    def _compute_fee_and_refund(self):
        for rec in self:
            if rec.allow_overrides_effective:
                fee = rec.fee_override or 0.0
                refund = rec.refund_override if rec.refund_override is not False else max(rec.subtotal_amount - fee, 0.0)
                # guard against negatives
                fee = max(fee, 0.0)
                refund = max(refund, 0.0)
                rec.fee_amount = fee
                rec.refund_amount = refund
                continue

            # No overrides: use policy
            fee = 0.0
            if rec.policy_id:
                if rec.policy_id.fee_type == 'fixed':
                    fee = rec.policy_id.fee_value or 0.0
                elif rec.policy_id.fee_type == 'percent':
                    fee = (rec.policy_id.fee_value or 0.0) * rec.subtotal_amount / 100.0
            fee = max(fee, 0.0)
            rec.fee_amount = fee
            rec.refund_amount = max(rec.subtotal_amount - fee, 0.0)

    # ----------------------------------------------------------------------------------
    # CRUD
    # ----------------------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('company_id'):
                vals['company_id'] = self.env.company.id
            if not vals.get('currency_id'):
                vals['currency_id'] = self.env.company.currency_id.id
            if not vals.get('name') or vals.get('name') == _("New"):
                vals['name'] = self.env['ir.sequence'].next_by_code("trakka.return.case") or _("New")
        recs = super().create(vals_list)
        return recs

    # ----------------------------------------------------------------------------------
    # Actions
    # ----------------------------------------------------------------------------------
    def _check_preapprove(self):
        for rec in self:
            missing = []
            if not rec.sale_order_id:
                missing.append("Sale Order")
            if not rec.picking_id:
                missing.append("Delivery Picking")
            if not rec.invoice_id:
                missing.append("Customer Invoice")
            if missing:
                raise ValidationError(_("Cannot approve. Missing: %s") % ", ".join(missing))

    def action_approve(self):
        """Freeze policy snapshot & move to approved."""
        for rec in self:
            if rec.state != 'draft':
                continue
            rec._check_preapprove()
            snapshot = {}
            if rec.policy_id:
                snapshot = {
                    "id": rec.policy_id.id,
                    "name": rec.policy_id.name,
                    "fee_type": rec.policy_id.fee_type,
                    "fee_value": rec.policy_id.fee_value,
                    "allow_overrides": rec.policy_id.allow_overrides,
                    "company_id": rec.policy_id.company_id.id if rec.policy_id.company_id else False,
                }
            rec.policy_snapshot = json.dumps(snapshot, ensure_ascii=False)
            rec.approved_by = self.env.user
            rec.approved_on = fields.Datetime.now()
            rec.state = 'approved'
        return True

    def action_reverse_picking_and_credit(self):
        """Minimal implementation:
        - Ensure approved/reversed.
        - (Stock return) Skipped for now (depends on specific quantities); keep field for future.
        - Create a draft credit note for `refund_amount` referencing original invoice, then post.
        - Link it back and set state to 'refunded'.
        """
        for rec in self:
            if rec.state not in ('approved', 'reversed'):
                raise UserError(_("Return Case must be Approved before reversing/crediting."))
            if not rec.invoice_id:
                raise UserError(_("No customer invoice linked."))

            # Build a minimal credit note using the first invoice line's product/account/taxes to avoid account errors.
            invoice = rec.invoice_id
            if not invoice.invoice_line_ids:
                raise UserError(_("The source invoice has no lines; can’t build a credit note safely."))

            base_line = invoice.invoice_line_ids[0]
            qty = 1.0
            price_unit = rec.refund_amount or 0.0
            if price_unit <= 0.0:
                raise UserError(_("Refund Amount must be greater than zero."))

            line_vals = {
                'name': _("Return Case %s") % (rec.name,),
                'quantity': qty,
                'price_unit': price_unit,
            }
            # Use product if available to auto-derive account; else fall back to account_id directly
            if base_line.product_id:
                line_vals['product_id'] = base_line.product_id.id
                line_vals['tax_ids'] = [(6, 0, base_line.tax_ids.ids)]
            else:
                # if no product, ensure an account is set
                if not base_line.account_id:
                    raise UserError(_("Cannot determine an income account to use on the credit note line."))
                line_vals['account_id'] = base_line.account_id.id
                line_vals['tax_ids'] = [(6, 0, base_line.tax_ids.ids)]

            move_vals = {
                'move_type': 'out_refund',
                'partner_id': invoice.partner_id.id,
                'invoice_origin': invoice.name or invoice.ref or invoice.invoice_origin,
                'invoice_date': fields.Date.context_today(self),
                'currency_id': rec.currency_id.id,
                'company_id': rec.company_id.id,
                'journal_id': invoice.journal_id.id,
                'invoice_line_ids': [(0, 0, line_vals)],
            }
            credit_move = self.env['account.move'].create(move_vals)
            # Post the credit note
            credit_move.action_post()

            rec.refund_move_id = credit_move.id
            rec.state = 'refunded'
        return True

    def action_cancel(self):
        """Cancel a return case unless already refunded."""
        for rec in self:
            if rec.state == "refunded":
                raise UserError(_("Cannot cancel a refunded case."))
            rec.state = "cancelled"
        return True

    # ----------------------------------------------------------------------------------
    # Constraints / SQL
    # ----------------------------------------------------------------------------------
    _sql_constraints = [
        ('name_company_uniq', 'unique(name, company_id)', 'Return Case reference must be unique per company.'),
    ]
