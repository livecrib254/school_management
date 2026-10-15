from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class SchoolBook(models.Model):
    _name = 'school.book'
    _description = 'Library Book'
    _order = 'name'

    name = fields.Char(string='Title', required=True, help='Book title as printed on the cover.')
    isbn = fields.Char(string='ISBN', help='ISBN printed on the back cover or copyright page; searchable.')
    author = fields.Char(help='Author or publisher body, e.g. "KICD".')
    publisher = fields.Char(help='Publisher of the edition held by the library.')
    subject_id = fields.Many2one('school.subject', string='Subject', help='Subject the book supports.')
    shelf = fields.Char(help='Shelf or section where the book is kept.')
    copies_total = fields.Integer(string='Copies', default=1, help='Number of copies the library owns.')
    copies_available = fields.Integer(compute='_compute_available',
                                      help='Copies on the shelf: total copies minus copies currently on loan. '
                                           'A book cannot be issued when none are available.')
    loan_ids = fields.One2many('school.library.loan', 'book_id')
    active = fields.Boolean(default=True)

    @api.depends('copies_total', 'loan_ids.state')
    def _compute_available(self):
        for book in self:
            out = len(book.loan_ids.filtered(lambda l: l.state in ('issued', 'overdue')))
            book.copies_available = book.copies_total - out


class SchoolLibraryLoan(models.Model):
    _name = 'school.library.loan'
    _description = 'Library Loan'
    _inherit = ['mail.thread']
    _order = 'date_issued desc, id desc'

    book_id = fields.Many2one('school.book', string='Book', required=True, help='Book being lent.')
    borrower_type = fields.Selection(
        [('student', 'Student'), ('staff', 'Staff')], default='student', required=True,
        help='Whether a student or a staff member is borrowing.')
    student_id = fields.Many2one('school.student', string='Student', help='Student borrowing the book.')
    employee_id = fields.Many2one('hr.employee', string='Staff Member', domain="[('is_school_staff', '=', True)]",
                                  help='Staff member borrowing the book. Only employees with a school role are listed.')
    date_issued = fields.Date(default=fields.Date.context_today, required=True, help='Day the book was handed out.')
    date_due = fields.Date(compute='_compute_date_due', store=True, readonly=False,
                           help='Return date, set to 14 days after issue by default (system parameter '
                                '"school_management.library_loan_days"). Can be changed per loan.')
    date_returned = fields.Date(readonly=True, help='Filled in when "Return Book" is clicked.')
    state = fields.Selection([
        ('issued', 'Issued'), ('overdue', 'Overdue'),
        ('returned', 'Returned'), ('lost', 'Lost'),
    ], default='issued', tracking=True, required=True,
        help='Issued loans past their due date become Overdue automatically each night.')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    fine_amount = fields.Monetary(compute='_compute_fine', currency_field='currency_id',
                                  help='Late-return fine: days late × the daily rate (5 by default, system '
                                       'parameter "school_management.library_fine_per_day"). For information; '
                                       'it is not invoiced automatically.')

    @api.depends('book_id.name', 'student_id.name', 'employee_id.name')
    def _compute_display_name(self):
        for rec in self:
            who = rec.student_id.name or rec.employee_id.name or ''
            rec.display_name = '%s - %s' % (rec.book_id.name or '', who)

    @api.depends('date_issued')
    def _compute_date_due(self):
        days = int(self.env['ir.config_parameter'].sudo().get_param(
            'school_management.library_loan_days', 14))
        for rec in self:
            rec.date_due = (rec.date_issued or fields.Date.context_today(rec)) + timedelta(days=days)

    @api.depends('date_due', 'date_returned', 'state')
    def _compute_fine(self):
        rate = float(self.env['ir.config_parameter'].sudo().get_param(
            'school_management.library_fine_per_day', 5))
        today = fields.Date.context_today(self)
        for rec in self:
            end = rec.date_returned or today
            late_days = (end - rec.date_due).days if rec.date_due and end > rec.date_due else 0
            rec.fine_amount = late_days * rate if rec.state != 'lost' else 0.0

    @api.constrains('book_id', 'state')
    def _check_availability(self):
        for rec in self:
            if rec.state in ('issued', 'overdue') and rec.book_id.copies_available < 0:
                raise ValidationError(self.env._('No copies of "%s" are available.', rec.book_id.name))

    @api.constrains('borrower_type', 'student_id', 'employee_id')
    def _check_borrower(self):
        for rec in self:
            if rec.borrower_type == 'student' and not rec.student_id:
                raise ValidationError(self.env._('Select the student borrowing the book.'))
            if rec.borrower_type == 'staff' and not rec.employee_id:
                raise ValidationError(self.env._('Select the staff member borrowing the book.'))

    def action_return(self):
        self.write({'state': 'returned', 'date_returned': fields.Date.context_today(self)})

    def action_lost(self):
        self.write({'state': 'lost'})

    @api.model
    def _cron_mark_overdue(self):
        today = fields.Date.context_today(self)
        self.search([('state', '=', 'issued'), ('date_due', '<', today)]).write({'state': 'overdue'})
