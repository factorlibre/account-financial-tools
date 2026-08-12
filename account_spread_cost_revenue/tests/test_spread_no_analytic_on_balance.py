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

        # Fixtures to validate invoices linked to a spread board.
        type_payable = self.env.ref('account.data_account_type_payable')
        type_receivable = self.env.ref('account.data_account_type_receivable')
        self.invoice_payable_account = self.env['account.account'].create({
            'name': 'Test payable',
            'code': 'TST321',
            'user_type_id': type_payable.id,
            'reconcile': True,
        })
        self.invoice_receivable_account = self.env['account.account'].create({
            'name': 'Test receivable',
            'code': 'TST123',
            'user_type_id': type_receivable.id,
            'reconcile': True,
        })
        # Balance-sheet account the spread swaps into the invoice move;
        # reconcilable so the spread<->invoice reconciliation can run.
        self.spread_balance_account = self.env['account.account'].create({
            'name': 'Test spread balance',
            'code': 'TST480',
            'user_type_id': self.env.ref(
                'account.data_account_type_current_liabilities').id,
            'reconcile': True,
        })
        self.assertTrue(
            self.spread_balance_account.user_type_id.include_initial_balance)
        self.partner = self.env['res.partner'].create({'name': 'Test partner'})

    def _create_spread(self, invoice_type, debit_account, credit_account,
                       amount=1200.0):
        spread = self.env['account.spread'].create({
            'name': 'test spread',
            'invoice_type': invoice_type,
            'debit_account_id': debit_account.id,
            'credit_account_id': credit_account.id,
            'period_number': 12,
            'period_type': 'month',
            'spread_date': '2026-01-01',
            'estimated_amount': amount,
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

    def _create_invoice(self, invoice_type):
        account = self.invoice_receivable_account
        if invoice_type == 'in_invoice':
            account = self.invoice_payable_account
        invoice = self.env['account.invoice'].create({
            'partner_id': self.partner.id,
            'account_id': account.id,
            'type': invoice_type,
        })
        self._add_invoice_line(invoice, 'spread test line')
        return invoice

    def _add_invoice_line(self, invoice, name):
        line_account = self.income_account
        if invoice.type == 'in_invoice':
            line_account = self.expense_account
        return self.env['account.invoice.line'].create({
            'invoice_id': invoice.id,
            'name': name,
            'quantity': 1.0,
            'price_unit': 1200.0,
            'account_id': line_account.id,
            'account_analytic_id': self.analytic_account.id,
            'analytic_tag_ids': [(6, 0, self.analytic_tag.ids)],
        })

    def _balance_move_lines(self, invoice):
        return invoice.move_id.line_ids.filtered(
            lambda ml: ml.account_id == self.spread_balance_account)

    def test_05_invoice_move_strips_balance_analytic(self):
        # The invoice move posts the spread balance account instead of the
        # invoice line account; with the flag enabled that line must not
        # carry the analytic data of the invoice line.
        self.assertTrue(self.company.spread_no_analytic_on_balance)
        invoice = self._create_invoice('in_invoice')
        spread = self._create_spread(
            'in_invoice', self.expense_account, self.spread_balance_account)
        invoice.invoice_line_ids.spread_id = spread
        invoice.action_invoice_open()
        balance_lines = self._balance_move_lines(invoice)
        self.assertTrue(balance_lines)
        for ml in balance_lines:
            self.assertFalse(
                ml.analytic_account_id,
                'Invoice balance line should not carry an analytic account')
            self.assertFalse(
                ml.analytic_tag_ids,
                'Invoice balance line should not carry analytic tags')
        # The spread keeps applying the analytic on its own moves.
        line = spread.line_ids[0]
        line.create_move()
        self.assertTrue(line.move_id)
        self._assert_split(line.move_id)

    def test_06_revenue_invoice_move_strips_balance_analytic(self):
        # Same as test_05 for a customer invoice: the swapped account is
        # the spread debit account (deferred income).
        self.assertTrue(self.company.spread_no_analytic_on_balance)
        invoice = self._create_invoice('out_invoice')
        spread = self._create_spread(
            'out_invoice', self.spread_balance_account, self.income_account)
        invoice.invoice_line_ids.spread_id = spread
        invoice.action_invoice_open()
        balance_lines = self._balance_move_lines(invoice)
        self.assertTrue(balance_lines)
        for ml in balance_lines:
            self.assertFalse(ml.analytic_account_id)
            self.assertFalse(ml.analytic_tag_ids)
        line = spread.line_ids[0]
        line.create_move()
        self.assertTrue(line.move_id)
        self._assert_split(line.move_id)

    def test_07_flag_off_keeps_invoice_move_analytic(self):
        # Opt-out: the invoice move keeps the analytic data on the swapped
        # balance line, exactly as before the fix.
        self.company.spread_no_analytic_on_balance = False
        invoice = self._create_invoice('in_invoice')
        spread = self._create_spread(
            'in_invoice', self.expense_account, self.spread_balance_account)
        invoice.invoice_line_ids.spread_id = spread
        invoice.action_invoice_open()
        balance_lines = self._balance_move_lines(invoice)
        self.assertTrue(balance_lines)
        for ml in balance_lines:
            self.assertEqual(ml.analytic_account_id, self.analytic_account)
            self.assertEqual(ml.analytic_tag_ids, self.analytic_tag)

    def test_08_spread_lines_are_never_grouped(self):
        # On a journal with the grouping option, two lines linked to
        # different spread boards share the grouping hashcode once the
        # analytic data is stripped. They must stay apart, because each
        # board reconciles against one line of the invoice entry, and a
        # merged line cannot serve more than one board.
        invoice = self._create_invoice('in_invoice')
        invoice.journal_id.group_invoice_lines = True
        first_line = invoice.invoice_line_ids
        second_line = self._add_invoice_line(invoice, 'spread test line 2')
        # Two lines without a spread board, which must still be merged.
        self._add_invoice_line(invoice, 'plain line')
        self._add_invoice_line(invoice, 'plain line')
        first_line.spread_id = self._create_spread(
            'in_invoice', self.expense_account, self.spread_balance_account)
        second_line.spread_id = self._create_spread(
            'in_invoice', self.expense_account, self.spread_balance_account)

        invoice.action_invoice_open()

        balance_lines = self._balance_move_lines(invoice)
        self.assertEqual(
            len(balance_lines), 2,
            'Lines linked to different spread boards must not be merged')
        self.assertEqual(
            set(balance_lines.mapped('name')),
            {'spread test line', 'spread test line 2'})
        plain_lines = invoice.move_id.line_ids.filtered(
            lambda ml: ml.account_id == self.expense_account)
        self.assertEqual(
            len(plain_lines), 1,
            'Lines without a spread board must keep being grouped')

        # Each board reconciles against its own invoice move line.
        spreads = first_line.spread_id + second_line.spread_id
        for spread in spreads:
            spread.line_ids[0].create_move()
        spreads.reconcile_spread_moves()
        for ml in balance_lines:
            self.assertTrue(
                ml.matched_credit_ids,
                'Every spread board must reconcile its own invoice line')

    def test_09_refund_lines_drop_the_spread_link(self):
        # Boundary of the feature: the credit note drops the link to the
        # board, so nothing swaps the account of its move and the analytic
        # data survives. Only the drop of the link is asserted here.
        invoice = self._create_invoice('in_invoice')
        invoice.invoice_line_ids.spread_id = self._create_spread(
            'in_invoice', self.expense_account, self.spread_balance_account)
        cleaned = self.env['account.invoice']._refund_cleanup_lines(
            invoice.invoice_line_ids)
        self.assertFalse(cleaned[0][2]['spread_id'])

    def test_10_criterion_read_from_the_spread_company(self):
        # The option is answered by the company of the board, not by the one
        # of the invoice: with the option off there, the analytic stays even
        # though the company of the invoice has it enabled.
        invoice = self._create_invoice('in_invoice')
        spread = self._create_spread(
            'in_invoice', self.expense_account, self.spread_balance_account)
        invoice.invoice_line_ids.spread_id = spread
        spread.company_id = self.env['res.company'].create({
            'name': 'Other company',
            'spread_no_analytic_on_balance': False,
        })
        self.assertTrue(self.company.spread_no_analytic_on_balance)
        move_lines = invoice.invoice_line_move_line_get()
        self.assertEqual(
            move_lines[0]['account_analytic_id'], self.analytic_account.id)

    def _invoice_lines_reconciled_by(self, spread):
        """Invoice move lines reconciled against the entry of this board."""
        matched = self.env['account.move.line']
        for ml in spread.line_ids[0].move_id.line_ids:
            matched |= ml.matched_debit_ids.mapped('debit_move_id')
            matched |= ml.matched_credit_ids.mapped('credit_move_id')
        return matched

    def _two_boards_on_repeated_description(self, invoice,
                                            second_amount=600.0):
        """Two lines described the same, each linked to its own board.

        The amounts differ by default, so that a crossed pairing between
        lines of different amount is detectable. Pass the same amount as the
        first line to exercise the tie instead.
        """
        invoice.journal_id.group_invoice_lines = True
        first_line = invoice.invoice_line_ids
        second_line = self._add_invoice_line(invoice, 'spread test line')
        second_line.price_unit = second_amount
        first_line.spread_id = self._create_spread(
            'in_invoice', self.expense_account, self.spread_balance_account)
        second_line.spread_id = self._create_spread(
            'in_invoice', self.expense_account, self.spread_balance_account,
            amount=second_amount)
        return first_line + second_line

    def _post_and_reconcile_boards(self, invoice, lines):
        invoice.action_invoice_open()
        spreads = lines.mapped('spread_id')
        for spread in spreads:
            spread.line_ids[0].create_move()
        spreads.reconcile_spread_moves()
        return spreads

    def test_11_repeated_description_pairs_each_board(self):
        # Two lines described the same are told apart by their amount, so
        # each board must reconcile its own line — the one carrying its own
        # amount, not the one of the other board.
        invoice = self._create_invoice('in_invoice')
        lines = self._two_boards_on_repeated_description(invoice)
        self._post_and_reconcile_boards(invoice, lines)

        balance_lines = self._balance_move_lines(invoice)
        self.assertEqual(len(balance_lines), 2)
        for invoice_line in lines:
            reconciled = self._invoice_lines_reconciled_by(
                invoice_line.spread_id) & balance_lines
            self.assertEqual(
                len(reconciled), 1,
                'Every board must reconcile exactly one invoice line')
            self.assertEqual(
                reconciled.debit, invoice_line.price_subtotal,
                'Every board must reconcile the line of its own amount')

    def test_12_ambiguous_description_reconciles_nothing(self):
        # Documented limit: a line without a board repeating both the
        # description and the balance account leaves the candidates
        # impossible to pair, and then nothing is reconciled.
        invoice = self._create_invoice('in_invoice')
        lines = self._two_boards_on_repeated_description(invoice)
        plain_line = self._add_invoice_line(invoice, 'spread test line')
        plain_line.account_id = self.spread_balance_account

        spreads = self._post_and_reconcile_boards(invoice, lines)

        for spread in spreads:
            self.assertFalse(self._invoice_lines_reconciled_by(spread))

    def test_13_repeated_description_and_amount_pairs_each_board(self):
        # With the amounts equal too, nothing but the position tells the
        # lines apart. Which of the two each board takes is indifferent —
        # the amounts are the same — but two boards taking the same line is
        # not: one of them would silently stay unreconciled.
        invoice = self._create_invoice('in_invoice')
        lines = self._two_boards_on_repeated_description(
            invoice, second_amount=1200.0)
        self._post_and_reconcile_boards(invoice, lines)

        balance_lines = self._balance_move_lines(invoice)
        self.assertEqual(len(balance_lines), 2)
        reconciled = self.env['account.move.line']
        for invoice_line in lines:
            own = self._invoice_lines_reconciled_by(
                invoice_line.spread_id) & balance_lines
            self.assertEqual(
                len(own), 1,
                'Every board must reconcile exactly one invoice line')
            reconciled |= own
        self.assertEqual(
            len(reconciled), 2,
            'No two boards may reconcile the same invoice move line')
