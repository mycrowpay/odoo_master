from odoo import SUPERUSER_ID, api

def ensure_finops_setup(cr, registry):
    env = api.Environment(cr, SUPERUSER_ID, {})
    company = env.company

    # get-or-create accounts
    A = env['account.account'].sudo().with_context(default_company_id=company.id, company_id=company.id)
    def get_acc(code, name, atype):
        acc = A.search([('code','=',code), ('company_id','=',company.id)], limit=1)
        if not acc:
            acc = A.create({'code': code, 'name': name, 'account_type': atype, 'company_id': company.id})
        return acc

    acc_esc = get_acc('ESC001', 'Trakka Escrow Liability', 'liability_current')
    acc_wlt = get_acc('WLT001', 'Trakka Seller Wallet (Liability)', 'liability_current')
    acc_bpl = get_acc('BPL001', 'Buyer Payout Liability', 'liability_current')
    acc_rhr = get_acc('RHR001', 'Returns Handling Revenue', 'income_other')

    # get-or-create journals and ensure default accounts
    J = env['account.journal'].sudo().with_context(default_company_id=company.id, company_id=company.id)
    def get_jrnl(code, name, jtype, default_acc):
        j = J.search([('code','=',code), ('company_id','=',company.id)], limit=1)
        if not j:
            j = J.create({'name': name, 'code': code, 'type': jtype, 'company_id': company.id, 'default_account_id': default_acc.id})
        elif not j.default_account_id:
            j.default_account_id = default_acc.id
        return j

    get_jrnl('ESC', 'Escrow Liability', 'general', acc_esc)
    get_jrnl('WLT', 'Seller Wallet', 'general', acc_wlt)
    get_jrnl('BPL', 'Buyer Payout Liability', 'bank', acc_bpl)
    get_jrnl('RHR', 'Returns Handling Revenue', 'general', acc_rhr)
