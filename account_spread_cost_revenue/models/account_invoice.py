# Copyright 2016-2019 Onestein (<https://www.onestein.eu>)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, models


class AccountInvoice(models.Model):
    _inherit = 'account.invoice'

    @api.multi
    def action_move_create(self):
        """Invoked when validating the invoices."""
        res = super().action_move_create()
        spreads = self.mapped('invoice_line_ids.spread_id')
        spreads.compute_spread_board()
        spreads.reconcile_spread_moves()
        return res

    @api.multi
    def invoice_line_move_line_get(self):
        """Copying expense/revenue account from spread to move lines.

        When the spread company strips the analytic data from balance
        lines, the swapped line of the invoice move must not carry it
        either (same criterion as the spread entries). These values are
        consumed as plain ones by ``line_get_convert``, hence ``False``
        instead of the x2many command used on the spread entries.
        """
        res = super().invoice_line_move_line_get()
        for line in res:
            invl_id = line.get('invl_id')
            invl = self.env['account.invoice.line'].browse(invl_id)
            if invl.spread_id:
                account = invl.spread_id._invoice_move_account(
                    invl.invoice_id.type)
                line['account_id'] = account.id
                company = invl.spread_id.company_id
                if company.spread_strips_analytic(account):
                    line['account_analytic_id'] = False
                    line['analytic_tag_ids'] = False
        return res

    @api.multi
    def group_lines(self, iml, line):
        """Keep the lines linked to a spread board out of the grouping.

        Each board reconciles itself against one line of the invoice entry
        (``account.spread._reconcile_spread_moves``), so two lines linked to
        different boards merged into one leave boards unreconciled. Once the
        analytic data is stripped from the swapped balance line, such lines
        do share the grouping hashcode of the standard module (which keys on
        account, taxes, product, maturity and analytic), so they are
        excluded from the merge here. The rest of the invoice keeps grouping
        as usual, and boards whose lines repeat the description are told
        apart there by their balance-sheet account and their amount.

        ``iml`` is filtered along with ``line`` even though the standard
        method only iterates the latter: they are documented as parallel and
        another module of the chain may rely on it.
        """
        self.ensure_one()
        if not self.journal_id.group_invoice_lines or len(iml) != len(line):
            return super().group_lines(iml, line)
        spread_line_ids = set(self.invoice_line_ids.filtered('spread_id').ids)
        if not spread_line_ids:
            return super().group_lines(iml, line)
        kept_apart = []
        rest_iml = []
        rest_line = []
        for vals, converted in zip(iml, line):
            if vals.get('invl_id') in spread_line_ids:
                kept_apart.append(converted)
            else:
                rest_iml.append(vals)
                rest_line.append(converted)
        return super().group_lines(rest_iml, rest_line) + kept_apart

    @api.multi
    def action_cancel(self):
        """Cancel the spread lines and their related moves when
        the invoice is canceled."""
        res = super().action_cancel()
        spread_lines = self.mapped('invoice_line_ids.spread_id.line_ids')
        moves = spread_lines.mapped('move_id')
        if moves:
            moves.button_cancel()
            moves.unlink()
        spread_lines.unlink()
        return res

    @api.model
    def _refund_cleanup_lines(self, lines):
        result = super()._refund_cleanup_lines(lines)
        for i, line in enumerate(lines):
            for name in line._fields.keys():
                if name == 'spread_id':
                    result[i][2][name] = False
                    break
        return result
