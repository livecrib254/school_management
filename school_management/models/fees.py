from odoo import api, fields, models


class SchoolFeeStructure(models.Model):
    _name = 'school.fee.structure'
    _description = 'Fee Structure'
    _order = 'name'

    name = fields.Char(required=True, help='For example "Grade 4 - Day - Term Fees".')
    year_id = fields.Many2one('school.academic.year', string='Academic Year',
                              help='Leave empty to use this structure every year.')
    term_id = fields.Many2one('school.term', string='Term',
                              help='Leave empty to charge the same amounts every term. When several structures '
                                   'match a student, the most specific one wins: a term-specific one first, then '
                                   'day/boarder-specific, then year-specific.')
    level_ids = fields.Many2many('school.grade.level', string='Grade Levels', required=True,
                                 help='Grade levels charged with this structure.')
    student_type = fields.Selection(
        [('all', 'All Students'), ('day', 'Day Scholars'), ('boarding', 'Boarders')],
        default='all', required=True,
        help='Restrict the structure to day scholars or boarders, e.g. a separate structure with boarding fees.')
    line_ids = fields.One2many('school.fee.structure.line', 'structure_id', string='Fee Items',
                               help='Each item becomes a line on the student\'s term invoice.')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    total_amount = fields.Monetary(compute='_compute_total', currency_field='currency_id',
                                   help='Total per student per term, before bursary discounts and transport.')
    active = fields.Boolean(default=True)

    @api.depends('line_ids.amount')
    def _compute_total(self):
        for rec in self:
            rec.total_amount = sum(rec.line_ids.mapped('amount'))


class SchoolFeeStructureLine(models.Model):
    _name = 'school.fee.structure.line'
    _description = 'Fee Structure Line'
    _order = 'structure_id, sequence, id'

    structure_id = fields.Many2one('school.fee.structure', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    product_id = fields.Many2one(
        'product.product', string='Fee Item', required=True,
        domain="[('type', '=', 'service')]",
        help='Fee item such as Tuition or Boarding. Its income account (set on the product) decides '
             'where the revenue is booked in Accounting.')
    description = fields.Char(compute='_compute_from_product', store=True, readonly=False,
                              help='Text printed on the invoice line. Defaults to the fee item name.')
    currency_id = fields.Many2one(related='structure_id.currency_id')
    amount = fields.Monetary(compute='_compute_from_product', store=True, readonly=False,
                             currency_field='currency_id',
                             help='Amount charged per student per term. Defaults to the fee item\'s price.')

    @api.depends('product_id')
    def _compute_from_product(self):
        for line in self:
            if line.product_id:
                line.description = line.product_id.name
                line.amount = line.product_id.list_price
            else:
                line.description = line.description
                line.amount = line.amount


class AccountMove(models.Model):
    _inherit = 'account.move'

    student_id = fields.Many2one('school.student', string='Student', index=True, copy=False,
                                 help='Student this fee invoice is for. Counts towards the student\'s fee balance.')
    school_term_id = fields.Many2one('school.term', string='School Term', index=True, copy=False,
                                     help='Term billed. A student is only invoiced once per term by the generator.')
    school_class_id = fields.Many2one(
        'school.class', string='Class', compute='_compute_school_class_id', store=True, readonly=False,
        copy=False, help='Student\'s class when the invoice was made. Kept as it was, so invoices reprinted after '
                         'promotion still show the class that was billed.')

    @api.depends('student_id')
    def _compute_school_class_id(self):
        for move in self:
            move.school_class_id = move.student_id.class_id

    school_other_balance = fields.Monetary(
        compute='_compute_school_account_summary', currency_field='company_currency_id',
        string='Other Balance', help='Student\'s balance apart from this invoice: arrears from earlier invoices, '
                                     'less unused payments and credit notes. Negative means the account is in credit.')
    school_total_due = fields.Monetary(
        compute='_compute_school_account_summary', currency_field='company_currency_id',
        string='Total Outstanding', help='Other balance plus what is still due on this invoice.')

    def _compute_school_account_summary(self):
        for move in self:
            if not move.student_id or move.move_type != 'out_invoice':
                move.school_other_balance = move.school_total_due = 0.0
                continue
            posted = move.state == 'posted'
            this_due = move.amount_residual_signed if posted else move.amount_total_signed
            balance = move.student_id.sudo().fee_balance
            move.school_other_balance = balance - (this_due if posted else 0.0)
            move.school_total_due = move.school_other_balance + this_due

    def _reverse_moves(self, default_values_list=None, cancel=False):
        # Credit notes stay on the student's account: copy the student, term and class.
        if not default_values_list:
            default_values_list = [{} for move in self]
        for move, default_values in zip(self, default_values_list):
            if move.student_id:
                default_values.setdefault('student_id', move.student_id.id)
                default_values.setdefault('school_term_id', move.school_term_id.id)
                default_values.setdefault('school_class_id', move.school_class_id.id)
        return super()._reverse_moves(default_values_list=default_values_list, cancel=cancel)

    def _post(self, soft=True):
        posted = super()._post(soft=soft)
        # A full refund ("Reverse" with cancel) is reconciled with its invoice by Odoo itself.
        if not self.env.context.get('move_reverse_cancel'):
            posted.filtered(
                lambda m: m.student_id and m.move_type in ('out_invoice', 'out_refund')
            )._school_apply_student_credits()
        return posted

    def _school_apply_student_credits(self):
        """Settle a newly posted student document against the student's open items.

        Invoice: use up advance payments, overpayments and credit notes, oldest first.
        Credit note: pay the invoice it reverses first, then the oldest open invoices.
        """
        Line = self.env['account.move.line']
        for move in self:
            student = move.student_id
            own = move.line_ids.filtered(
                lambda l: l.account_id.account_type == 'asset_receivable' and not l.reconciled)
            if not own:
                continue
            is_invoice = move.move_type == 'out_invoice'
            counterparts = Line.search([
                ('account_id', '=', own.account_id[:1].id),
                ('company_id', '=', move.company_id.id),
                ('parent_state', '=', 'posted'),
                ('reconciled', '=', False),
                ('move_id', '!=', move.id),
                ('amount_residual', '<' if is_invoice else '>', 0),
                '|', ('move_id.student_id', '=', student.id),
                ('move_id.origin_payment_id.student_id', '=', student.id),
            ], order='date_maturity, date, id')
            if not is_invoice and move.reversed_entry_id:
                counterparts = counterparts.sorted(lambda l: l.move_id != move.reversed_entry_id)
            for counterpart in counterparts:
                own = own.filtered(lambda l: not l.reconciled)
                if not own:
                    break
                (counterpart + own).reconcile()


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    student_id = fields.Many2one(
        'school.student', string='Student', index=True, copy=False,
        help='Student this payment is for. Set automatically when paying a student\'s fee invoices; set it on '
             'an advance payment so it counts in the student\'s fee balance and is applied to the next invoice.')


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    def _school_student_vals(self, lines):
        moves = lines.move_id
        if len(moves.student_id) == 1 and all(moves.mapped('student_id')):
            return {'student_id': moves.student_id.id}
        return {}

    def _create_payment_vals_from_wizard(self, batch_result):
        vals = super()._create_payment_vals_from_wizard(batch_result)
        vals.update(self._school_student_vals(batch_result['lines']))
        return vals

    def _create_payment_vals_from_batch(self, batch_result):
        vals = super()._create_payment_vals_from_batch(batch_result)
        vals.update(self._school_student_vals(batch_result['lines']))
        return vals
