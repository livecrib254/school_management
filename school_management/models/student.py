import operator

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class SchoolStudent(models.Model):
    _name = 'school.student'
    _description = 'Student'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'
    _rec_names_search = ['name', 'admission_no', 'upi']

    name = fields.Char(string='Full Name', required=True, tracking=True,
                       help='Full name as on the birth certificate. Printed on report cards and invoices.')
    admission_no = fields.Char(
        string='Admission No.', readonly=True, copy=False, default='New', index=True,
        help='Assigned automatically when the student is created (ADM/year/number). Searchable from the student list.')
    upi = fields.Char(string='NEMIS UPI', help='Unique Personal Identifier from the Ministry of Education NEMIS system.')
    birth_cert_no = fields.Char(string='Birth Certificate No.', help='Entry number on the birth certificate.')
    image_1920 = fields.Image(max_width=1920, max_height=1920,
                              help='Passport-style photo. JPEG or PNG; large photos are resized automatically.')
    image_128 = fields.Image(related='image_1920', max_width=128, max_height=128, store=True)
    partner_id = fields.Many2one('res.partner', string='Contact', readonly=True,
                                 copy=False, ondelete='restrict',
                                 help='Contact record created automatically for the student. Invoices go to the '
                                      'fee-paying guardian instead, when there is one.')
    gender = fields.Selection(
        [('male', 'Male'), ('female', 'Female'), ('other', 'Other')], tracking=True,
        help='Used for boys/girls statistics and to check hostel allocations against boys\' or girls\' hostels.')
    date_of_birth = fields.Date(help='The age is calculated from it.')
    age = fields.Integer(compute='_compute_age', help='Age in completed years, calculated from the date of birth.')
    nationality_id = fields.Many2one(
        'res.country', string='Nationality', default=lambda self: self.env.ref('base.ke', False))
    admission_date = fields.Date(default=fields.Date.context_today,
                                 help='Date the student joined the school.')
    previous_school = fields.Char(help='School attended before joining, if any.')

    class_id = fields.Many2one('school.class', string='Class', tracking=True,
                               help='Current class. Changing it records the move in Class History. A student '
                                    'must have a class to be enrolled, and the class capacity is enforced.')
    level_id = fields.Many2one(related='class_id.level_id', store=True, string='Grade Level')
    year_id = fields.Many2one(related='class_id.year_id', store=True, string='Academic Year')
    education_system = fields.Selection(related='level_id.education_system', store=True)
    student_type = fields.Selection(
        [('day', 'Day Scholar'), ('boarding', 'Boarder')], default='day',
        required=True, tracking=True,
        help='Day scholars can use school transport; boarders can be given a hostel bed. It also selects '
             'day or boarding fee structures. End the transport subscription or hostel bed before switching.')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('enrolled', 'Enrolled'),
        ('suspended', 'Suspended'),
        ('graduated', 'Graduated'),
        ('transferred', 'Transferred'),
        ('withdrawn', 'Withdrawn'),
    ], default='draft', tracking=True, required=True,
        help='Only enrolled students appear on registers and mark sheets, get fee invoices and count in '
             'class sizes and statistics.')

    guardian_ids = fields.One2many('school.student.guardian', 'student_id', string='Guardians',
                                   help='Parents and guardians of the student and their role: primary contact, '
                                        'fee payer, emergency contact.')
    primary_guardian_id = fields.Many2one(
        'res.partner', compute='_compute_guardians', string='Primary Guardian',
        help='The guardian marked as primary contact, or the first guardian listed.')
    billing_partner_id = fields.Many2one(
        'res.partner', compute='_compute_guardians', string='Billing Contact',
        help='Who fee invoices are addressed to: the guardian marked "Pays Fees", otherwise the primary guardian.')
    guardian_phone = fields.Char(compute='_compute_guardians', string='Guardian Phone',
                                 help='Phone number of the primary guardian.')

    medical_notes = fields.Text(help='Allergies, conditions or medication staff should know about.')
    special_needs = fields.Text(string='Special Needs / Learning Support',
                                help='Learning support, accommodations or special needs information.')
    fee_discount_percent = fields.Float(
        string='Fee Discount (%)',
        help='Bursary, scholarship or sibling discount. Applied to every line of the fee invoices '
             'generated from now on; invoices already created are not changed.')

    enrollment_ids = fields.One2many('school.student.enrollment', 'student_id', string='Class History',
                                     help='Every class the student has been in, recorded automatically.')
    transport_subscription_ids = fields.One2many('school.transport.subscription', 'student_id')
    hostel_allocation_ids = fields.One2many('school.hostel.allocation', 'student_id')
    loan_ids = fields.One2many('school.library.loan', 'student_id')

    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    fee_balance = fields.Monetary(compute='_compute_fees', currency_field='currency_id', search='_search_fee_balance',
                                  help='What the student owes, all terms combined: unpaid fee invoices less advance '
                                       'payments and unused credit notes. Negative means the account is in credit.')
    invoice_count = fields.Integer(compute='_compute_fees')
    attendance_rate = fields.Float(compute='_compute_attendance_rate', string='Attendance (%)',
                                   help='Share of days marked present or late on confirmed registers.')
    report_card_count = fields.Integer(compute='_compute_counts')
    open_loan_count = fields.Integer(compute='_compute_counts')
    active = fields.Boolean(default=True)

    @api.depends('date_of_birth')
    def _compute_age(self):
        today = fields.Date.context_today(self)
        for rec in self:
            dob = rec.date_of_birth
            rec.age = (today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))) if dob else 0

    @api.depends('guardian_ids.is_primary', 'guardian_ids.is_fee_payer',
                 'guardian_ids.partner_id.phone', 'partner_id')
    def _compute_guardians(self):
        for rec in self:
            primary = rec.guardian_ids.filtered('is_primary')[:1] or rec.guardian_ids[:1]
            payer = rec.guardian_ids.filtered('is_fee_payer')[:1] or primary
            rec.primary_guardian_id = primary.partner_id
            rec.billing_partner_id = payer.partner_id or rec.partner_id
            rec.guardian_phone = primary.partner_id.phone

    # Fee account. A student's account is every posted receivable item linked to the student:
    # fee invoices and credit notes (student_id) and payments (account.payment.student_id).
    # The balance is what is still open on them, so advance payments and unused credit notes
    # reduce it. _school_fee_ledger() lists the same items and always ends on the same balance.
    #
    # The aggregates below are read with sudo: teachers, registrars and librarians open
    # student records without having access to invoices, registers or report cards.
    def _school_receivable_domain(self):
        return [
            ('account_id.account_type', '=', 'asset_receivable'),
            ('parent_state', '=', 'posted'),
            '|', ('move_id.student_id', 'in', self.ids),
            ('move_id.origin_payment_id.student_id', 'in', self.ids),
        ]

    def _school_unbooked_payment_domain(self):
        # Payments on a journal without an outstanding receipts account have no journal entry
        # until bank reconciliation, so they do not reduce any invoice yet.
        return [('student_id', 'in', self.ids), ('move_id', '=', False),
                ('state', '=', 'in_process'), ('payment_type', '=', 'inbound')]

    def _search_fee_balance(self, op, value):
        # Lets lists filter on the balance ("Owes Fees"); computed for all visible students at once.
        ops = {'>': operator.gt, '>=': operator.ge, '<': operator.lt, '<=': operator.le,
               '=': operator.eq, '!=': operator.ne}
        if op not in ops:
            return NotImplemented
        students = self.with_context(active_test=False).search([])
        return [('id', 'in', [s.id for s in students if ops[op](s.fee_balance, value or 0.0)])]

    def _phone_get_number_fields(self):
        # SMS sent from a student (Send SMS, fee reminders) go to the primary guardian.
        return ['guardian_phone']

    def _compute_fees(self):
        Line = self.env['account.move.line'].sudo()
        balances = {}
        for move, residual in Line._read_group(
                self._school_receivable_domain() + [('reconciled', '=', False)],
                ['move_id'], ['amount_residual:sum']):
            student = move.student_id or move.origin_payment_id.student_id
            balances[student.id] = balances.get(student.id, 0.0) + residual
        for student, amount in self.env['account.payment'].sudo()._read_group(
                self._school_unbooked_payment_domain(), ['student_id'], ['amount_company_currency_signed:sum']):
            balances[student.id] = balances.get(student.id, 0.0) - amount
        counts = {s.id: c for s, c in self.env['account.move'].sudo()._read_group(
            [('student_id', 'in', self.ids), ('move_type', 'in', ('out_invoice', 'out_refund')),
             ('state', '!=', 'cancel')], ['student_id'], ['__count'])}
        for rec in self:
            rec.fee_balance = balances.get(rec.id, 0.0)
            rec.invoice_count = counts.get(rec.id, 0)

    def _school_fee_ledger(self):
        """Every charge and payment on the student's fee account, oldest first, with a running
        balance. Returns (entries, closing_balance); the closing balance equals fee_balance."""
        self.ensure_one()
        _ = self.env._
        lines = self.env['account.move.line'].sudo().search(self._school_receivable_domain(), order='date, id')
        entries = []
        for line in lines:
            move = line.move_id
            if move.move_type == 'out_invoice':
                description = _('Fees - %s', move.school_term_id.display_name) if move.school_term_id else _('Fees')
            elif move.move_type == 'out_refund':
                description = _('Credit note') + (' - %s' % move.reversed_entry_id.name if move.reversed_entry_id else '')
            else:
                payment = move.origin_payment_id
                description = payment.memo or _('Payment')
            entries.append({'date': line.date, 'ref': move.name, 'description': description,
                            'debit': line.debit, 'credit': line.credit})
            # Matches with items outside the student's account, e.g. a payment recorded without
            # the student, or a student payment used for a sibling's invoice.
            for partial in line.matched_debit_ids | line.matched_credit_ids:
                line_is_debit = partial.debit_move_id == line
                other = partial.credit_move_id if line_is_debit else partial.debit_move_id
                if other in lines:
                    continue
                entries.append({
                    'date': partial.max_date or other.date,
                    'ref': other.move_id.name,
                    'description': _('Payment') if line_is_debit else _('Applied to %s', other.move_id.name),
                    'debit': 0.0 if line_is_debit else partial.amount,
                    'credit': partial.amount if line_is_debit else 0.0,
                })
        for payment in self.env['account.payment'].sudo().search(self._school_unbooked_payment_domain()):
            entries.append({'date': payment.date, 'ref': payment.name, 'description': payment.memo or _('Payment'),
                            'debit': 0.0, 'credit': payment.amount_company_currency_signed})
        entries.sort(key=lambda e: e['date'])
        balance = 0.0
        for entry in entries:
            balance += entry['debit'] - entry['credit']
            entry['balance'] = balance
        return entries, balance

    def _compute_attendance_rate(self):
        Line = self.env['school.attendance.line'].sudo()
        data = Line._read_group(
            [('student_id', 'in', self.ids), ('attendance_id.state', '=', 'confirmed')],
            ['student_id', 'status'], ['__count'])
        totals, present = {}, {}
        for student, status, count in data:
            totals[student.id] = totals.get(student.id, 0) + count
            if status in ('present', 'late'):
                present[student.id] = present.get(student.id, 0) + count
        for rec in self:
            total = totals.get(rec.id, 0)
            rec.attendance_rate = (present.get(rec.id, 0) / total * 100.0) if total else 0.0

    def _compute_counts(self):
        cards = {s.id: c for s, c in self.env['school.report.card'].sudo()._read_group(
            [('student_id', 'in', self.ids)], ['student_id'], ['__count'])}
        loans = {s.id: c for s, c in self.env['school.library.loan'].sudo()._read_group(
            [('student_id', 'in', self.ids), ('state', 'in', ('issued', 'overdue'))],
            ['student_id'], ['__count'])}
        for rec in self:
            rec.report_card_count = cards.get(rec.id, 0)
            rec.open_loan_count = loans.get(rec.id, 0)

    @api.constrains('guardian_ids')
    def _check_primary_guardian(self):
        for rec in self:
            if len(rec.guardian_ids.filtered('is_primary')) > 1:
                raise ValidationError(self.env._('Only one guardian can be marked as primary.'))

    @api.constrains('student_type')
    def _check_student_type_services(self):
        for rec in self.filtered(lambda s: s.student_type == 'boarding'):
            if rec.sudo().transport_subscription_ids.filtered(lambda s: s.state == 'active'):
                raise ValidationError(self.env._(
                    '%s still has an active transport subscription. End it under '
                    'Transport > Subscriptions before changing the student to a boarder.', rec.name))
        for rec in self.filtered(lambda s: s.student_type == 'day'):
            if rec.sudo().hostel_allocation_ids.filtered(lambda a: a.state == 'active'):
                raise ValidationError(self.env._(
                    '%s still has an active hostel bed. End the allocation under '
                    'Hostel > Bed Allocations before changing the student to a day scholar.', rec.name))

    @api.constrains('class_id', 'state')
    def _check_class_capacity(self):
        Student = self.sudo()
        for school_class in self.filtered(lambda s: s.state == 'enrolled').class_id:
            if not school_class.capacity:
                continue
            enrolled = Student.search_count([
                ('class_id', '=', school_class.id), ('state', '=', 'enrolled')])
            if enrolled > school_class.capacity:
                raise ValidationError(self.env._(
                    'Class %(name)s is full: %(count)s enrolled students for a capacity of %(cap)s.',
                    name=school_class.name, count=enrolled, cap=school_class.capacity))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('admission_no', 'New') == 'New':
                vals['admission_no'] = self.env['ir.sequence'].next_by_code('school.student') or 'New'
            if not vals.get('partner_id'):
                partner = self.env['res.partner'].sudo().create({'name': vals.get('name')})
                vals['partner_id'] = partner.id
        students = super().create(vals_list)
        for student in students.filtered('class_id'):
            student._log_enrollment()
        return students

    def write(self, vals):
        res = super().write(vals)
        if 'class_id' in vals:
            for student in self.filtered('class_id'):
                student._log_enrollment()
        if 'name' in vals:
            for student in self.filtered('partner_id'):
                student.partner_id.sudo().name = student.name
        return res

    def _log_enrollment(self):
        self.ensure_one()
        last = self.enrollment_ids.sorted('id')[-1:]
        if last and last.class_id == self.class_id:
            return
        self.env['school.student.enrollment'].create({
            'student_id': self.id,
            'class_id': self.class_id.id,
        })

    # state transitions
    def action_enroll(self):
        for rec in self:
            if not rec.class_id:
                raise ValidationError(self.env._('Assign a class before enrolling %s.', rec.name))
        self.write({'state': 'enrolled'})

    def action_suspend(self):
        self.write({'state': 'suspended'})

    def action_graduate(self):
        self.write({'state': 'graduated'})

    def action_transfer(self):
        self.write({'state': 'transferred'})

    def action_withdraw(self):
        self.write({'state': 'withdrawn'})

    def action_reset(self):
        self.write({'state': 'draft'})

    # smart buttons
    def action_view_invoices(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('account.action_move_out_invoice_type')
        action['domain'] = [('student_id', '=', self.id), ('move_type', 'in', ('out_invoice', 'out_refund'))]
        action['context'] = {
            'default_move_type': 'out_invoice',
            'default_student_id': self.id,
            'default_partner_id': self.billing_partner_id.id,
            'school_invoice_list': True,
        }
        return action

    def action_message_guardian(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Message to Guardian'),
            'res_model': 'school.guardian.message',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_student_id': self.id,
                'default_partner_id': self.primary_guardian_id.id,
                'default_class_id': self.class_id.id,
                'default_level_id': self.level_id.id,
            },
        }

    def action_view_report_cards(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Report Cards'),
            'res_model': 'school.report.card',
            'view_mode': 'list,form',
            'domain': [('student_id', '=', self.id)],
            'context': {'default_student_id': self.id, 'default_class_id': self.class_id.id},
        }

    def action_view_attendance(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Attendance'),
            'res_model': 'school.attendance.line',
            'view_mode': 'list',
            'domain': [('student_id', '=', self.id)],
        }

    def action_view_loans(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Library Loans'),
            'res_model': 'school.library.loan',
            'view_mode': 'list,form',
            'domain': [('student_id', '=', self.id)],
            'context': {'default_student_id': self.id, 'default_borrower_type': 'student'},
        }


class SchoolStudentGuardian(models.Model):
    _name = 'school.student.guardian'
    _description = 'Student Guardian'
    _order = 'is_primary desc, id'

    student_id = fields.Many2one('school.student', required=True, ondelete='cascade')
    partner_id = fields.Many2one('res.partner', string='Guardian', required=True,
                                 domain="[('is_school_guardian', '=', True)]",
                                 help='Only parents and guardians are listed. Type a new name and choose '
                                      '"Create and edit" to add a guardian.')
    relation = fields.Selection([
        ('father', 'Father'), ('mother', 'Mother'), ('guardian', 'Guardian'),
        ('sibling', 'Sibling'), ('other', 'Other'),
    ], default='guardian', required=True, help='How this person is related to the student.')
    is_primary = fields.Boolean(string='Primary Contact',
                                help='Main person the school contacts. Only one guardian per student can be primary.')
    is_fee_payer = fields.Boolean(string='Pays Fees',
                                  help='Fee invoices are addressed to this guardian. If nobody is ticked, '
                                       'the primary contact is billed.')
    is_emergency = fields.Boolean(string='Emergency Contact', help='Call this person in an emergency.')
    phone = fields.Char(related='partner_id.phone')
    email = fields.Char(related='partner_id.email')


class SchoolStudentEnrollment(models.Model):
    _name = 'school.student.enrollment'
    _description = 'Student Class History'
    _order = 'date_from desc, id desc'

    student_id = fields.Many2one('school.student', required=True, ondelete='cascade')
    class_id = fields.Many2one('school.class', string='Class', required=True)
    level_id = fields.Many2one(related='class_id.level_id', store=True)
    year_id = fields.Many2one(related='class_id.year_id', store=True)
    date_from = fields.Date(default=fields.Date.context_today, help='Date the student joined this class.')
    note = fields.Char(help='Optional remark, e.g. "Repeating" or "Transferred from Grade 5 West".')


class ResPartner(models.Model):
    _inherit = 'res.partner'

    guardian_line_ids = fields.One2many('school.student.guardian', 'partner_id', string='Children',
                                        help='Students this person is a parent or guardian of.')
    school_student_count = fields.Integer(compute='_compute_school_student_count',
                                          help='Number of students linked to this guardian.')
    is_school_guardian = fields.Boolean(
        string='Parent / Guardian', compute='_compute_is_school_guardian', store=True,
        readonly=False, index=True,
        help='Set automatically once the contact is linked to a student. Only these contacts '
             'are offered when choosing a student guardian.')
    guardian_national_id = fields.Char(string='National ID / Passport No.', copy=False,
                                       help='Must be unique: it is used to recognise a guardian who already has '
                                            'a child in the school when a new admission is enrolled.')
    guardian_occupation = fields.Char(string='Occupation', help='Occupation or employer of the guardian.')

    @api.depends('guardian_line_ids')
    def _compute_school_student_count(self):
        for partner in self:
            partner.school_student_count = len(partner.guardian_line_ids.student_id)

    @api.depends('guardian_line_ids')
    def _compute_is_school_guardian(self):
        for partner in self:
            partner.is_school_guardian = partner.is_school_guardian or bool(partner.guardian_line_ids)

    @api.constrains('guardian_national_id')
    def _check_guardian_national_id(self):
        for partner in self.filtered('guardian_national_id'):
            duplicate = self.sudo().search([
                ('guardian_national_id', '=ilike', partner.guardian_national_id.strip()),
                ('id', '!=', partner.id)], limit=1)
            if duplicate:
                raise ValidationError(self.env._(
                    'National ID %(id)s is already recorded for %(name)s.',
                    id=partner.guardian_national_id, name=duplicate.display_name))
