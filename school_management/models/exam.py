from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class SchoolExam(models.Model):
    _name = 'school.exam'
    _description = 'Exam / Assessment'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'

    name = fields.Char(required=True, tracking=True, help='For example "Mid-Term Exam" or "Opener CAT".')
    exam_type = fields.Selection([
        ('cat', 'CAT / Opener'),
        ('midterm', 'Mid-Term'),
        ('endterm', 'End-Term'),
        ('mock', 'Mock'),
        ('assessment', 'CBC Assessment'),
    ], default='cat', required=True, help='Kind of assessment, for filtering and reporting.')
    class_id = fields.Many2one('school.class', string='Class', required=True,
                               help='Class sitting the exam. "Generate Mark Sheet" creates a row for each '
                                    'enrolled student and each subject of this class.')
    term_id = fields.Many2one(
        'school.term', string='Term', required=True,
        default=lambda self: self.env['school.term']._get_current(),
        help='Term the exam counts towards on the report card.')
    year_id = fields.Many2one(related='term_id.year_id', store=True)
    date = fields.Date(default=fields.Date.context_today, help='Date the exam was sat.')
    max_mark = fields.Float(string='Out Of', default=100.0, required=True,
                            help='Maximum mark of each paper. Marks are converted to a percentage of this '
                                 'before grading, so exams out of 50 and out of 100 compare fairly.')
    weight = fields.Float(
        default=100.0,
        help='How much this exam counts in the term average compared with the other exams of the term. '
             'Example: CAT 30 and End-Term 70 make the End-Term count more than twice as much. '
             'Equal weights give a simple average.')
    state = fields.Selection(
        [('draft', 'Draft'), ('ongoing', 'Marking'), ('done', 'Done')],
        default='draft', tracking=True, required=True,
        help='Draft: being set up. Marking: mark sheet generated, teachers enter marks. Done: all marks in '
             'and locked; only Done exams are used on report cards.')
    result_ids = fields.One2many('school.exam.result', 'exam_id', string='Results')
    result_count = fields.Integer(compute='_compute_result_count')

    @api.depends('result_ids')
    def _compute_result_count(self):
        for rec in self:
            rec.result_count = len(rec.result_ids)

    @api.constrains('max_mark')
    def _check_max_mark(self):
        for rec in self:
            if rec.max_mark <= 0:
                raise ValidationError(self.env._('"Out Of" must be greater than zero.'))

    def action_generate_results(self):
        Result = self.env['school.exam.result']
        for rec in self:
            if not rec.class_id.subject_line_ids:
                raise UserError(self.env._('Allocate subjects to class %s first.', rec.class_id.name))
            students = rec.class_id.student_ids.filtered(lambda s: s.state == 'enrolled')
            existing = {(r.student_id.id, r.subject_id.id) for r in rec.result_ids}
            vals = [
                {'exam_id': rec.id, 'student_id': student.id, 'subject_id': line.subject_id.id}
                for student in students
                for line in rec.class_id.subject_line_ids
                if (student.id, line.subject_id.id) not in existing
            ]
            if vals:
                Result.create(vals)
        self.filtered(lambda r: r.state == 'draft').write({'state': 'ongoing'})

    def action_start(self):
        self.write({'state': 'ongoing'})

    def action_done(self):
        for rec in self:
            pending = rec.result_ids.filtered(lambda r: not r.is_absent and not r.mark_entered)
            if pending:
                raise UserError(self.env._(
                    '%(exam)s still has %(count)s unmarked result(s). Enter a mark or tick Absent '
                    'for each student before closing the exam.',
                    exam=rec.display_name, count=len(pending)))
        self.write({'state': 'done'})

    def action_draft(self):
        self.write({'state': 'draft'})

    def action_view_results(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Results'),
            'res_model': 'school.exam.result',
            'view_mode': 'list,form',
            'domain': [('exam_id', '=', self.id)],
            'context': {'default_exam_id': self.id, 'search_default_group_subject': 1},
        }


class SchoolExamResult(models.Model):
    _name = 'school.exam.result'
    _description = 'Exam Result'
    _order = 'exam_id, subject_id, student_id'

    exam_id = fields.Many2one('school.exam', required=True, ondelete='cascade')
    student_id = fields.Many2one('school.student', required=True)
    subject_id = fields.Many2one('school.subject', required=True)
    mark = fields.Float(help='Raw mark scored, between 0 and the exam\'s "Out Of".')
    mark_entered = fields.Boolean(
        string='Marked', copy=False,
        help='Ticked automatically when a mark is typed in. Unmarked rows are ignored on report cards and '
             'block "Mark Done". Tick it yourself to record a genuine score of 0.')
    is_absent = fields.Boolean(string='Absent',
                               help='Student missed the paper. Absent papers are left out of the subject average '
                                    'instead of counting as 0.')
    max_mark = fields.Float(related='exam_id.max_mark')
    exam_state = fields.Selection(related='exam_id.state', string='Exam Status')
    percentage = fields.Float(compute='_compute_grade', store=True,
                              help='Mark as a percentage of "Out Of"; the grade is read from this.')
    grade = fields.Char(compute='_compute_grade', store=True,
                        help='Grade from the active grade scale: CBC performance level or KCSE letter grade.')
    points = fields.Integer(compute='_compute_grade', store=True, help='Points of the grade on the active grade scale.')
    descriptor = fields.Char(compute='_compute_grade', store=True,
                             help='Meaning of the grade, e.g. "Meets Expectations".')
    remarks = fields.Char(help='Teacher\'s note on this paper.')
    class_id = fields.Many2one(related='exam_id.class_id', store=True)
    term_id = fields.Many2one(related='exam_id.term_id', store=True)

    _exam_student_subject_uniq = models.Constraint(
        'UNIQUE (exam_id, student_id, subject_id)',
        'A result already exists for this student and subject.',
    )

    @api.depends('mark', 'mark_entered', 'is_absent', 'exam_id.max_mark',
                 'exam_id.class_id.level_id.education_system')
    def _compute_grade(self):
        Scale = self.env['school.grade.scale']
        scales = {}
        for rec in self:
            if rec.is_absent or not rec.mark_entered or not rec.exam_id.max_mark:
                rec.percentage = 0.0
                rec.grade = False
                rec.points = 0
                rec.descriptor = False
                continue
            system = rec.exam_id.class_id.level_id.education_system
            if system not in scales:
                scales[system] = Scale._get_scale(system)
            pct = rec.mark / rec.exam_id.max_mark * 100.0
            band = scales[system]._band(pct)
            rec.percentage = pct
            rec.grade = band.grade or False
            rec.points = band.points
            rec.descriptor = band.descriptor or False

    @api.constrains('mark', 'exam_id')
    def _check_mark(self):
        for rec in self:
            if rec.mark < 0 or rec.mark > rec.exam_id.max_mark:
                raise ValidationError(
                    self.env._('Marks for %(student)s must be between 0 and %(max)s.',
                               student=rec.student_id.name, max=rec.exam_id.max_mark))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'mark' in vals and 'mark_entered' not in vals:
                vals['mark_entered'] = True
        return super().create(vals_list)

    def write(self, vals):
        if 'mark' in vals and 'mark_entered' not in vals:
            vals = dict(vals, mark_entered=True)
        if not self.env.su and ({'mark', 'mark_entered', 'is_absent'} & set(vals)) \
                and any(rec.exam_id.state == 'done' for rec in self):
            raise UserError(self.env._('Marks of a completed exam cannot be changed. Reset the exam first.'))
        return super().write(vals)


class SchoolReportCard(models.Model):
    _name = 'school.report.card'
    _description = 'Report Card'
    _inherit = ['mail.thread']
    _order = 'term_id desc, class_id, position, student_id'

    student_id = fields.Many2one('school.student', required=True, tracking=True)
    class_id = fields.Many2one('school.class', string='Class', required=True)
    term_id = fields.Many2one('school.term', string='Term', required=True)
    year_id = fields.Many2one(related='term_id.year_id', store=True)
    company_id = fields.Many2one(related='student_id.company_id', store=True)
    education_system = fields.Selection(related='class_id.level_id.education_system')
    line_ids = fields.One2many('school.report.card.line', 'card_id', string='Subjects')
    total_marks = fields.Float(readonly=True, help='Sum of the subject averages (in %).')
    total_points = fields.Integer(readonly=True, help='Sum of the subject grade points.')
    mean_percentage = fields.Float(string='Mean (%)', readonly=True,
                                   help='Average of the subject scores. Used for the mean grade and class position.')
    mean_grade = fields.Char(readonly=True, help='Grade of the mean score on the active grade scale.')
    mean_descriptor = fields.Char(readonly=True, help='Meaning of the mean grade, e.g. "Meets Expectations".')
    position = fields.Integer(readonly=True,
                              help='Rank in the class by mean score; equal means share a position. '
                                   'Students with no graded subject are not ranked.')
    class_size = fields.Integer(readonly=True, help='Number of ranked students in the class this term.')
    attendance_percent = fields.Float(string='Attendance (%)', readonly=True,
                                      help='Share of days present or late on confirmed registers during the term.')
    class_teacher_comment = fields.Text(help='Printed on the report card. Locked once the card is published.')
    principal_comment = fields.Text(string="Head Teacher's Comment",
                                    help='Printed on the report card. Locked once the card is published.')
    state = fields.Selection(
        [('draft', 'Draft'), ('published', 'Published')], default='draft', tracking=True, required=True,
        help='Published cards are visible to parents on the portal and are no longer recomputed. '
             'Unpublish to correct and recompute.')

    @api.depends('student_id.name', 'term_id.display_name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = '%s - %s' % (rec.student_id.name or '', rec.term_id.display_name or '')

    _student_term_uniq = models.Constraint(
        'UNIQUE (student_id, term_id)',
        'A report card already exists for this student and term.',
    )

    def action_compute(self):
        """Recompute draft cards from the marked results of completed exams of the term.

        Published cards are left untouched; unpublish a card to refresh it.
        """
        Result = self.env['school.exam.result']
        Scale = self.env['school.grade.scale']
        cards = self.filtered(lambda c: c.state == 'draft')
        for card in cards:
            scale = Scale._get_scale(card.class_id.level_id.education_system)
            results = Result.search([
                ('student_id', '=', card.student_id.id),
                ('term_id', '=', card.term_id.id),
                ('exam_id.state', '=', 'done'),
                ('mark_entered', '=', True),
                ('is_absent', '=', False),
            ])
            by_subject = {}
            for res in results:
                by_subject.setdefault(res.subject_id, []).append(res)

            existing = {line.subject_id.id: line for line in card.line_ids}
            averages = []
            for subject, rows in by_subject.items():
                weight = sum(r.exam_id.weight for r in rows) or 1.0
                avg = sum(r.percentage * r.exam_id.weight for r in rows) / weight
                band = scale._band(avg)
                vals = {
                    'percentage': avg,
                    'grade': band.grade or False,
                    'points': band.points,
                    'descriptor': band.descriptor or False,
                }
                averages.append((avg, band.points))
                if subject.id in existing:
                    existing[subject.id].write(vals)
                else:
                    card.write({'line_ids': [(0, 0, dict(vals, subject_id=subject.id))]})
            card.line_ids.filtered(lambda l: l.subject_id not in by_subject).unlink()

            mean = sum(a for a, _p in averages) / len(averages) if averages else 0.0
            band = scale._band(mean) if averages else self.env['school.grade.scale.line']
            card.write({
                'total_marks': sum(a for a, _p in averages),
                'total_points': sum(p for _a, p in averages),
                'mean_percentage': mean,
                'mean_grade': band.grade or False,
                'mean_descriptor': band.descriptor or False,
                'attendance_percent': card._compute_attendance_percent(),
            })
        cards._update_positions()

    def _compute_attendance_percent(self):
        self.ensure_one()
        lines = self.env['school.attendance.line'].search([
            ('student_id', '=', self.student_id.id),
            ('date', '>=', self.term_id.date_start),
            ('date', '<=', self.term_id.date_end),
            ('attendance_id.state', '=', 'confirmed'),
        ])
        if not lines:
            return 0.0
        present = len(lines.filtered(lambda l: l.status in ('present', 'late')))
        return present / len(lines) * 100.0

    def _update_positions(self):
        """Rank every card of the affected class/term groups; equal means share a position.

        Cards without any graded subject are not ranked. Only draft cards are rewritten,
        so a published card keeps the position it was published with.
        """
        for class_id, term_id in {(card.class_id.id, card.term_id.id) for card in self}:
            cards = self.search([('class_id', '=', class_id), ('term_id', '=', term_id)])
            ranked = cards.filtered('line_ids').sorted('mean_percentage', reverse=True)
            positions = {}
            previous, last_pos = None, 0
            for index, card in enumerate(ranked, start=1):
                mean = round(card.mean_percentage, 2)
                if mean != previous:
                    last_pos, previous = index, mean
                positions[card.id] = last_pos
            for card in cards.filtered(lambda c: c.state == 'draft'):
                card.write({'position': positions.get(card.id, 0), 'class_size': len(ranked)})

    def action_publish(self):
        self.write({'state': 'published'})

    def action_draft(self):
        self.write({'state': 'draft'})


class SchoolReportCardLine(models.Model):
    _name = 'school.report.card.line'
    _description = 'Report Card Line'
    _order = 'card_id, subject_id'

    card_id = fields.Many2one('school.report.card', required=True, ondelete='cascade')
    subject_id = fields.Many2one('school.subject', required=True)
    percentage = fields.Float(string='Score (%)',
                              help='Term average for the subject, weighted by each exam\'s weight. '
                                   'Absent and unmarked papers are left out.')
    grade = fields.Char(help='Grade of the subject average on the active grade scale.')
    points = fields.Integer(help='Points of the subject grade.')
    descriptor = fields.Char(help='Meaning of the grade, e.g. "Exceeds Expectations".')
    teacher_comment = fields.Char(string='Comment', help='Subject teacher\'s remark, printed on the report card.')
