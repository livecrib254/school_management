from odoo import api, fields, models


class SchoolAttendance(models.Model):
    _name = 'school.attendance'
    _description = 'Attendance Register'
    _inherit = ['mail.thread']
    _order = 'date desc, class_id'

    class_id = fields.Many2one('school.class', string='Class', required=True,
                               help='Class the register is for. Its enrolled students are loaded automatically.')
    date = fields.Date(required=True, default=fields.Date.context_today,
                       help='Day of the register. Only one register per class per day is allowed.')
    user_id = fields.Many2one('res.users', string='Taken By', default=lambda self: self.env.user,
                              help='Person who took the register.')
    state = fields.Selection(
        [('draft', 'Draft'), ('confirmed', 'Confirmed')], default='draft', tracking=True, required=True,
        help='Only confirmed registers count towards attendance rates, report cards and the dashboard. '
             'Confirm once the roll call is complete.')
    line_ids = fields.One2many('school.attendance.line', 'attendance_id', string='Students')
    total_count = fields.Integer(compute='_compute_counts', help='Number of students on the register.')
    present_count = fields.Integer(compute='_compute_counts', help='Students marked present or late.')
    absent_count = fields.Integer(compute='_compute_counts', help='Students marked absent (excused not included).')

    @api.depends('class_id.name', 'date')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = '%s - %s' % (rec.class_id.name or '', rec.date or '')

    @api.depends('line_ids.status')
    def _compute_counts(self):
        for rec in self:
            rec.total_count = len(rec.line_ids)
            rec.present_count = len(rec.line_ids.filtered(lambda l: l.status in ('present', 'late')))
            rec.absent_count = len(rec.line_ids.filtered(lambda l: l.status == 'absent'))

    _class_date_uniq = models.Constraint(
        'UNIQUE (class_id, date)',
        'An attendance register already exists for this class and date.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records.filtered(lambda r: not r.line_ids):
            rec._load_students()
        return records

    def _load_students(self):
        self.ensure_one()
        existing = self.line_ids.student_id
        students = self.class_id.student_ids.filtered(
            lambda s: s.state == 'enrolled' and s not in existing)
        self.write({'line_ids': [(0, 0, {'student_id': s.id}) for s in students]})

    def action_load_students(self):
        for rec in self:
            rec._load_students()

    def action_mark_all_present(self):
        self.line_ids.write({'status': 'present'})

    def action_confirm(self):
        self.write({'state': 'confirmed'})

    def action_draft(self):
        self.write({'state': 'draft'})


class SchoolAttendanceLine(models.Model):
    _name = 'school.attendance.line'
    _description = 'Attendance Line'
    _order = 'attendance_id, student_id'

    attendance_id = fields.Many2one('school.attendance', required=True, ondelete='cascade')
    student_id = fields.Many2one('school.student', required=True)
    status = fields.Selection([
        ('present', 'Present'), ('absent', 'Absent'),
        ('late', 'Late'), ('excused', 'Excused'),
    ], default='present', required=True,
        help='Present and Late count as attended. Absent and Excused count as not attended in the attendance rate.')
    remarks = fields.Char(help='Reason for absence or lateness, e.g. "Sick - parent called".')
    date = fields.Date(related='attendance_id.date', store=True)
    class_id = fields.Many2one(related='attendance_id.class_id', store=True)

    _attendance_student_uniq = models.Constraint(
        'UNIQUE (attendance_id, student_id)',
        'A student can only appear once per register.',
    )
