# Copyright 2026 FactorLibre
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.modules.module import get_module_resource
from odoo.tests import common
from odoo.tools import convert_file


class TestSpreadNoAnalyticOnBalance(common.TransactionCase):
    def _load(self, module, *args):
        convert_file(
            self.cr,
            'account_spread_cost_revenue',
            get_module_resource(module, *args),
            {}, 'init', False, 'test', self.registry._assertion_report)

    def setUp(self):
        super().setUp()
        self._load('account', 'test', 'account_minimal_test.xml')

        self.company = self.env.user.company_id

        # P&L accounts (include_initial_balance == False)
        self.expense_account = self.env.ref(
            'account_spread_cost_revenue.a_expense')
        self.income_account = self.env.ref(
            'account_spread_cost_revenue.a_sale')
        # Balance-sheet account (include_initial_balance == True), e.g. 480
        self.balance_account = self.env.ref(
            'account_spread_cost_revenue.prepayements')
        self.journal = self.env.ref(
            'account_spread_cost_revenue.miscellaneous_journal')

        # Guard the fixture assumptions the whole suite relies on.
        self.assertFalse(
            self.expense_account.user_type_id.include_initial_balance)
        self.assertFalse(
            self.income_account.user_type_id.include_initial_balance)
        self.assertTrue(
            self.balance_account.user_type_id.include_initial_balance)

        self.analytic_account = self.env['account.analytic.account'].create({
            'name': 'Test cost center',
        })
        self.analytic_tag = self.env.ref('analytic.tag_contract')

    def _create_spread(self, invoice_type, debit_account, credit_account):
        spread = self.env['account.spread'].create({
            'name': 'test spread',
            'invoice_type': invoice_type,
            'debit_account_id': debit_account.id,
            'credit_account_id': credit_account.id,
            'period_number': 12,
            'period_type': 'month',
            'spread_date': '2026-01-01',
            'estimated_amount': 1200.0,
            'journal_id': self.journal.id,
            'account_analytic_id': self.analytic_account.id,
            'analytic_tag_ids': [(6, 0, self.analytic_tag.ids)],
        })
        spread.compute_spread_board()
        return spread

    def _assert_split(self, move):
        """P&L lines keep the analytic data; balance lines must not."""
        self.assertTrue(move.line_ids)
        for ml in move.line_ids:
            if ml.account_id.user_type_id.include_initial_balance:
                self.assertFalse(
                    ml.analytic_account_id,
                    'Balance line should not carry an analytic account')
                self.assertFalse(
                    ml.analytic_tag_ids,
                    'Balance line should not carry analytic tags')
            else:
                self.assertEqual(ml.analytic_account_id, self.analytic_account)
                self.assertEqual(ml.analytic_tag_ids, self.analytic_tag)

    def test_01_cost_spread_default_strips_balance_analytic(self):
        # Default behaviour (flag enabled): debit expense (P&L),
        # credit prepaid (balance).
        self.assertTrue(self.company.spread_no_analytic_on_balance)
        spread = self._create_spread(
            'in_invoice', self.expense_account, self.balance_account)
        line = spread.line_ids[0]
        line.create_move()
        self.assertTrue(line.move_id)
        self._assert_split(line.move_id)

    def test_02_revenue_spread_default_strips_balance_analytic(self):
        # Revenue spread: debit deferred income (balance), credit income (P&L).
        spread = self._create_spread(
            'out_invoice', self.balance_account, self.income_account)
        line = spread.line_ids[0]
        line.create_move()
        self.assertTrue(line.move_id)
        self._assert_split(line.move_id)

    def test_03_flag_off_keeps_analytic_on_all_lines(self):
        # Opt-out: legacy behaviour keeps analytic on every line, balance too.
        self.company.spread_no_analytic_on_balance = False
        spread = self._create_spread(
            'in_invoice', self.expense_account, self.balance_account)
        line = spread.line_ids[0]
        line.create_move()
        self.assertTrue(line.move_id)
        balance_lines = line.move_id.line_ids.filtered(
            lambda ml: ml.account_id == self.balance_account)
        self.assertTrue(balance_lines)
        for ml in line.move_id.line_ids:
            self.assertEqual(ml.analytic_account_id, self.analytic_account)
            self.assertEqual(ml.analytic_tag_ids, self.analytic_tag)

    def test_04_refund_spread_strips_balance_analytic(self):
        # The discriminator is account-driven, so refunds behave like the
        # base invoice: the balance line never carries analytic data.
        spread = self._create_spread(
            'in_refund', self.expense_account, self.balance_account)
        line = spread.line_ids[0]
        line.create_move()
        self.assertTrue(line.move_id)
        self._assert_split(line.move_id)
