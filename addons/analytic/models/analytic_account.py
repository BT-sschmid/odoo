# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.osv import expression
from odoo.exceptions import ValidationError


class AccountAnalyticDistribution(models.Model):
    _name = 'account.analytic.distribution'
    _rec_name = 'account_id'

    account_id = fields.Many2one('account.analytic.account', string='Analytic Account', required=True)
    percentage = fields.Float(string='Percentage', required=True, default=100.0)
    name = fields.Char(string='Name', related='account_id.name')
    tag_id = fields.Many2one('account.analytic.tag', string="Parent tag", required=True)

    _sql_constraints = [
        ('check_percentage', 'CHECK(percentage >= 0 AND percentage <= 100)',
         'The percentage of an analytic distribution should be between 0 and 100.')
    ]

class AccountAnalyticTag(models.Model):
    _name = 'account.analytic.tag'
    _description = 'Analytic Tags'
    name = fields.Char(string='Analytic Tag', index=True, required=True)
    color = fields.Integer('Color Index')
    active = fields.Boolean(default=True, help="Set active to false to hide the Analytic Tag without removing it.")
    active_analytic_distribution = fields.Boolean('Analytic Distribution')
    analytic_distribution_ids = fields.One2many('account.analytic.distribution', 'tag_id', string="Analytic Accounts")
    company_id = fields.Many2one('res.company', string='Company')

class AccountAnalyticGroup(models.Model):
    _name = 'account.analytic.group'
    _description = 'Analytic Categories'
    _parent_store = True
    _rec_name = 'complete_name'

    name = fields.Char(required=True)
    description = fields.Text(string='Description')
    parent_id = fields.Many2one('account.analytic.group', string="Parent", ondelete='cascade')
    parent_left = fields.Integer('Left Parent', index=True)
    parent_right = fields.Integer('Right Parent', index=True)
    children_ids = fields.One2many('account.analytic.group', 'parent_id', string="Childrens")
    complete_name = fields.Char('Complete Name', compute='_compute_complete_name', store=True)
    company_id = fields.Many2one('res.company', string='Company')

    @api.depends('name', 'parent_id.complete_name')
    def _compute_complete_name(self):
        for group in self:
            if group.parent_id:
                group.complete_name = '%s / %s' % (group.parent_id.complete_name, group.name)
            else:
                group.complete_name = group.name

class AccountAnalyticAccount(models.Model):
    _name = 'account.analytic.account'
    _inherit = ['mail.thread']
    _description = 'Analytic Account'
    _order = 'code, name asc'

    @api.multi
    def _compute_debit_credit_balance(self):
        res_currency_obj = self.env['res.currency']
        analytic_line_obj = self.env['account.analytic.line']
        domain = [('account_id', 'in', self.mapped('id'))]
        if self._context.get('from_date', False):
            domain.append(('date', '>=', self._context['from_date']))
        if self._context.get('to_date', False):
            domain.append(('date', '<=', self._context['to_date']))
        if self._context.get('tag_ids'):
            tag_domain = expression.OR([[('tag_ids', 'in', [tag])] for tag in self._context['tag_ids']])
            domain = expression.AND([domain, tag_domain])
        if self._context.get('company_ids'):
            domain.append(('company_id', 'in', self._context['company_ids']))

        user_currency = self.env.user.company_id.currency_id
        account_amounts = analytic_line_obj.search_read(domain, ['account_id', 'amount', 'currency_id'])
        account_ids = set([line['account_id'][0] for line in account_amounts])
        data_debit = {account_id: 0.0 for account_id in account_ids}
        data_credit = {account_id: 0.0 for account_id in account_ids}
        for account_amount in account_amounts:
            currency_id = account_amount['currency_id'][0]
            amount = res_currency_obj.browse(currency_id).compute(account_amount['amount'], user_currency)
            if amount < 0.0:
                data_debit[account_amount['account_id'][0]] += amount
            else:
                data_credit[account_amount['account_id'][0]] += amount

        for account in self:
            account.debit = abs(data_debit.get(account.id, 0.0))
            account.credit = data_credit.get(account.id, 0.0)
            account.balance = account.credit - account.debit

    name = fields.Char(string='Analytic Account', index=True, required=True, track_visibility='onchange')
    code = fields.Char(string='Reference', index=True, track_visibility='onchange')
    active = fields.Boolean('Active', help="If the active field is set to False, it will allow you to hide the account without removing it.", default=True)

    group_id = fields.Many2one('account.analytic.group', string='Group')

    line_ids = fields.One2many('account.analytic.line', 'account_id', string="Analytic Lines")

    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.user.company_id)

    # use auto_join to speed up name_search call
    partner_id = fields.Many2one('res.partner', string='Customer', auto_join=True, track_visibility='onchange')

    balance = fields.Monetary(compute='_compute_debit_credit_balance', string='Balance')
    debit = fields.Monetary(compute='_compute_debit_credit_balance', string='Debit')
    credit = fields.Monetary(compute='_compute_debit_credit_balance', string='Credit')

    currency_id = fields.Many2one(related="company_id.currency_id", string="Currency", readonly=True)

    @api.multi
    def name_get(self):
        res = []
        for analytic in self:
            name = analytic.name
            if analytic.code:
                name = '[' + analytic.code + '] ' + name
            if analytic.partner_id:
                name = name + ' - ' + analytic.partner_id.commercial_partner_id.name
            res.append((analytic.id, name))
        return res

    @api.model
    def name_search(self, name='', args=None, operator='ilike', limit=100):
        if operator not in ('ilike', 'like', '=', '=like', '=ilike'):
            return super(AccountAnalyticAccount, self).name_search(name, args, operator, limit)
        args = args or []
        domain = ['|', ('code', operator, name), ('name', operator, name)]
        partners = self.env['res.partner'].search([('name', operator, name)], limit=limit)
        if partners:
            domain = ['|'] + domain + [('partner_id', 'in', partners.ids)]
        recs = self.search(domain + args, limit=limit)
        return recs.name_get()


class AccountAnalyticLine(models.Model):
    _name = 'account.analytic.line'
    _description = 'Analytic Line'
    _order = 'date desc, id desc'

    @api.model
    def _default_user(self):
        return self.env.context.get('user_id', self.env.user.id)

    name = fields.Char('Description', required=True)
    date = fields.Date('Date', required=True, index=True, default=fields.Date.context_today)
    amount = fields.Monetary('Amount', required=True, default=0.0)
    unit_amount = fields.Float('Quantity', default=0.0)
    account_id = fields.Many2one('account.analytic.account', 'Analytic Account', required=True, ondelete='restrict', index=True)
    partner_id = fields.Many2one('res.partner', string='Partner')
    user_id = fields.Many2one('res.users', string='User', default=_default_user)
    tag_ids = fields.Many2many('account.analytic.tag', 'account_analytic_line_tag_rel', 'line_id', 'tag_id', string='Tags', copy=True)
    company_id = fields.Many2one('res.company', string='Company', required=True, readonly=True, default=lambda self: self.env.user.company_id)
    currency_id = fields.Many2one(related="company_id.currency_id", string="Currency", readonly=True, store=True)
    group_id = fields.Many2one('account.analytic.group', related='account_id.group_id', store=True, readonly=True)

    @api.multi
    @api.constrains('company_id', 'account_id')
    def _check_company_id(self):
        for line in self:
            if line.account_id.company_id and line.company_id.id != line.account_id.company_id.id:
                raise ValidationError(_('The selected account belongs to another company that the one you\'re trying to create an analytic item for'))
