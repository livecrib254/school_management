from odoo import api, fields, models
from odoo.exceptions import ValidationError


class SchoolAcademicYear(models.Model):
    _name = 'school.academic.year'
    _description = 'Academic Year'
    _order = 'date_start desc'

    name = fields.Char(required=True, help='How the year is shown everywhere, for example "2026".')
    date_start = fields.Date(string='Start Date', required=True,
                             help='First day of the school year (normally the opening day of Term 1).')
    date_end = fields.Date(string='End Date', required=True,
                           help='Last day of the school year (normally the closing day of Term 3).')
    state = fields.Selection(
        [('draft', 'Draft'), ('open', 'Open'), ('closed', 'Closed')],
        default='draft', required=True,
        help='Draft: being prepared. Open: the current year; new classes and admissions default to it. '
             'Closed: finished, kept for history.')
    term_ids = fields.One2many('school.term', 'year_id', string='Terms',
                               help='The terms of this year. Exams, report cards and fee invoices are per term.')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    active = fields.Boolean(default=True)

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for rec in self:
            if rec.date_end < rec.date_start:
                raise ValidationError(self.env._('The end date must be after the start date.'))

    def action_open(self):
        self.write({'state': 'open'})

    def action_close(self):
        self.write({'state': 'closed'})

    def action_draft(self):
        self.write({'state': 'draft'})


class SchoolTerm(models.Model):
    _name = 'school.term'
    _description = 'Term'
    _order = 'date_start'

    name = fields.Char(required=True, help='For example "Term 1". Shown with the year, e.g. "Term 1 - 2026".')
    year_id = fields.Many2one('school.academic.year', string='Academic Year',
                              required=True, ondelete='cascade',
                              help='The school year this term belongs to.')
    date_start = fields.Date(string='Start Date', required=True,
                             help='Opening day. The term covering today is used as the default term '
                                  'for exams, report cards and fee invoices.')
    date_end = fields.Date(string='End Date', required=True,
                           help='Closing day. Attendance on report cards is counted from the start to this date.')
    next_term_date = fields.Date(string='Next Term Opens',
                                 help='Printed on the report card so parents know when school reopens.')

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for rec in self:
            if rec.date_end < rec.date_start:
                raise ValidationError(self.env._('The end date must be after the start date.'))

    @api.depends('name', 'year_id.name')
    def _compute_display_name(self):
        for term in self:
            term.display_name = '%s - %s' % (term.name, term.year_id.name) if term.year_id else term.name

    @api.model
    def _get_current(self):
        today = fields.Date.context_today(self)
        return self.search([('date_start', '<=', today), ('date_end', '>=', today)], limit=1)


class SchoolGradeLevel(models.Model):
    _name = 'school.grade.level'
    _description = 'Grade Level'
    _order = 'sequence, id'

    name = fields.Char(required=True, help='For example "Grade 4" or "Form 2". Used in class names.')
    code = fields.Char(help='Short code for reports and lists, for example "G4" or "F2".')
    sequence = fields.Integer(default=10, help='Order of the levels, from the youngest to the oldest.')
    education_system = fields.Selection(
        [('cbc', 'CBC'), ('844', '8-4-4')], default='cbc', required=True,
        help='Decides which grade scale marks are graded with: the CBC performance levels '
             '(EE/ME/AE/BE) or the 8-4-4 KCSE letter grades (A to E).')
    stage = fields.Selection(help='The schooling stage, used to group levels.', selection=[
        ('pre_primary', 'Pre-Primary'),
        ('lower_primary', 'Lower Primary'),
        ('upper_primary', 'Upper Primary'),
        ('junior_secondary', 'Junior Secondary'),
        ('senior_secondary', 'Senior Secondary'),
        ('secondary_844', 'Secondary (8-4-4)'),
    ])
    next_level_id = fields.Many2one(
        'school.grade.level', string='Promotes To',
        help='The level students move up to at the end of the year. The Year-End Rollover uses it '
             'to promote classes. Leave empty for the final level: those students graduate.')
    active = fields.Boolean(default=True)


class SchoolClass(models.Model):
    _name = 'school.class'
    _description = 'Class / Stream'
    _inherit = ['mail.thread']
    _order = 'level_id, name'

    name = fields.Char(compute='_compute_name', store=True, readonly=False,
                       help='Built from the grade level and stream, e.g. "Grade 4 East". You can overwrite it.')
    level_id = fields.Many2one('school.grade.level', string='Grade Level', required=True,
                               help='The grade or form of this class. It decides the grading scale '
                                    'and which fee structure applies to its students.')
    stream = fields.Char(help='Name of the stream when a grade has several classes, for example East, '
                              'West or Blue. Leave empty if the grade has a single class.')
    year_id = fields.Many2one(
        'school.academic.year', string='Academic Year', required=True,
        default=lambda self: self.env['school.academic.year'].search(
            [('state', '=', 'open')], limit=1),
        help='Classes are created per year; the Year-End Rollover creates next year\'s classes.')
    class_teacher_id = fields.Many2one(
        'hr.employee', string='Class Teacher', domain="[('is_teacher', '=', True)]",
        tracking=True, help='Teacher in charge of the class. Only staff with a teaching role are listed.')
    capacity = fields.Integer(default=40, help='Maximum number of enrolled students. Enrolling or '
                                               'promoting beyond it is refused. 0 means no limit.')
    room = fields.Char(help='Classroom where the class normally meets.')
    student_ids = fields.One2many('school.student', 'class_id', string='Students')
    student_count = fields.Integer(compute='_compute_student_count', help='Number of enrolled students in the class.')
    subject_line_ids = fields.One2many('school.class.subject', 'class_id', string='Subjects',
                                       help='Subjects taught in this class. Mark sheets are generated for these subjects.')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    active = fields.Boolean(default=True)

    @api.depends('level_id.name', 'stream')
    def _compute_name(self):
        for rec in self:
            rec.name = ' '.join(filter(None, [rec.level_id.name, rec.stream])) or rec.name

    @api.depends('student_ids.state')
    def _compute_student_count(self):
        for rec in self:
            rec.student_count = len(rec.student_ids.filtered(lambda s: s.state == 'enrolled'))

    @api.constrains('capacity')
    def _check_capacity(self):
        # Covers lowering the capacity below the current roll. Adding students is checked
        # on school.student, because students are assigned to a class from the student side.
        for rec in self:
            if rec.capacity < 0:
                raise ValidationError(self.env._('Capacity cannot be negative.'))
            if rec.capacity and rec.student_count > rec.capacity:
                raise ValidationError(self.env._(
                    'Class %(name)s already has %(count)s enrolled students, more than a capacity of %(cap)s.',
                    name=rec.name, count=rec.student_count, cap=rec.capacity))

    def action_view_students(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Students'),
            'res_model': 'school.student',
            'view_mode': 'list,form',
            'domain': [('class_id', '=', self.id)],
            'context': {'default_class_id': self.id},
        }


class SchoolSubject(models.Model):
    _name = 'school.subject'
    _description = 'Subject / Learning Area'
    _order = 'name'

    name = fields.Char(required=True, help='Subject or CBC learning area, for example "Mathematics" '
                                           'or "Integrated Science". Printed on report cards.')
    code = fields.Char(help='Short code used in lists, for example "MATH".')
    education_system = fields.Selection(
        [('both', 'All'), ('cbc', 'CBC'), ('844', '8-4-4')], default='both', required=True,
        help='Which curriculum offers this subject. "All" for subjects taught in both CBC and 8-4-4.')
    is_core = fields.Boolean(string='Core / Compulsory', default=True,
                             help='Ticked for compulsory subjects; untick for optional subjects and electives.')
    active = fields.Boolean(default=True)


class SchoolClassSubject(models.Model):
    _name = 'school.class.subject'
    _description = 'Class Subject Allocation'
    _order = 'class_id, subject_id'

    class_id = fields.Many2one('school.class', required=True, ondelete='cascade')
    subject_id = fields.Many2one('school.subject', required=True, help='Subject taught in this class.')
    teacher_id = fields.Many2one(
        'hr.employee', string='Teacher', domain="[('is_teacher', '=', True)]",
        help='Subject teacher for this class. Suggested automatically when the subject is put on the timetable.')
    periods_per_week = fields.Integer(default=4, help='Number of lessons of this subject per week.')

    _class_subject_uniq = models.Constraint(
        'UNIQUE (class_id, subject_id)',
        'This subject is already allocated to the class.',
    )
