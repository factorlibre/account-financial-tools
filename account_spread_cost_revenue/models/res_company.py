# Copyright 2018-2019 Onestein (<https://www.onestein.eu>)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    default_spread_revenue_account_id = fields.Many2one(
        'account.account', string='Revenue Spread Account')

    default_spread_expense_account_id = fields.Many2one(
        'account.account', string='Expense Spread Account')

    default_spread_revenue_journal_id = fields.Many2one(
        'account.journal', string='Revenue Spread Journal')

    default_spread_expense_journal_id = fields.Many2one(
        'account.journal', string='Expense Spread Journal')

    allow_spread_planning = fields.Boolean(
        default=True,
        help="Disable this option if you do not want to allow the "
             "spreading before the invoice is validated.")
    force_move_auto_post = fields.Boolean(
        'Auto-post spread lines',
        help="Enable this option if you want to post automatically the "
             "accounting moves of all the spreads.")
    auto_archive = fields.Boolean(
        'Auto-archive spread',
        help="Enable this option if you want the cron job to automatically "
             "archive the spreads when all lines are posted.")
    spread_no_analytic_on_balance = fields.Boolean(
        'No analytic on balance accounts',
        default=True,
        help="If enabled, spread journal entries keep the analytic account "
             "and tags only on profit & loss lines, never on balance-sheet "
             "lines (accounts whose type carries the initial balance "
             "forward).")

    @api.multi
    def spread_strips_analytic(self, account):
        """Whether the spread must leave ``account`` without analytic data.

        Single criterion for both halves of the feature (the lines of the
        spread entries and the swapped line of the invoice entry): the
        company option plus a balance-sheet account, identified by
        ``include_initial_balance`` on its account type. It is always
        answered by the company of the spread board, so both halves are
        ruled by the same record — which is required on the board, hence the
        singleton contract.
        """
        self.ensure_one()
        return bool(self.spread_no_analytic_on_balance
                    and account.user_type_id.include_initial_balance)
