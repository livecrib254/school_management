from odoo import api, fields, models
from odoo.exceptions import ValidationError

WEEKDAYS = [
    ('0', 'Monday'), ('1', 'Tuesday'), ('2', 'Wednesday'),
    ('3', 'Thursday'), ('4', 'Friday'),
]


class SchoolPeriod(models.Model):
    _name = 'school.period'
    _description = 'Lesson Period'
    _order = 'sequence, start_time'

    name = fields.Char(required=True, help='For example "Lesson 1" or "Lunch".')
    sequence = fields.Integer(default=10)
    start_time = fields.Float(required=True, help='Start time in hours and minutes, e.g. 08:00.')
    end_time = fields.Float(required=True, help='End time in hours and minutes, e.g. 08:40. Must be after the start.')
    is_break = fields.Boolean(string='Break / Lunch',
                              help='Breaks and lunch appear in the day plan but cannot have lessons scheduled.')

    @api.constrains('start_time', 'end_time')
    def _check_times(self):
        for rec in self:
            if rec.end_time <= rec.start_time:
                raise ValidationError(self.env._('A period must end after it starts.'))


class SchoolTimetableEntry(models.Model):
    _name = 'school.timetable.entry'
    _description = 'Timetable Entry'
    _order = 'class_id, weekday, period_id'

    class_id = fields.Many2one('school.class', string='Class', required=True, ondelete='cascade',
                               help='Class having the lesson. A class can only have one lesson per period.')
    year_id = fields.Many2one(related='class_id.year_id', store=True, string='Academic Year')
    weekday = fields.Selection(WEEKDAYS, required=True, help='Day of the week the lesson takes place.')
    period_id = fields.Many2one('school.period', string='Period', required=True,
                                domain="[('is_break', '=', False)]",
                                help='Lesson slot. Breaks are not listed.')
    subject_id = fields.Many2one('school.subject', required=True,
                                 help='Subject taught. The subject teacher of the class is filled in automatically.')
    teacher_id = fields.Many2one('hr.employee', string='Teacher', domain="[('is_teacher', '=', True)]",
                                 help='A teacher cannot be booked in two classes in the same period of the same year.')
    room = fields.Char(help='Room for this lesson if different from the class\'s usual room, e.g. a laboratory.')

    @api.onchange('class_id', 'subject_id')
    def _onchange_teacher(self):
        if self.class_id and self.subject_id:
            line = self.class_id.subject_line_ids.filtered(lambda l: l.subject_id == self.subject_id)[:1]
            if line.teacher_id:
                self.teacher_id = line.teacher_id

    _class_slot_uniq = models.Constraint(
        'UNIQUE (class_id, weekday, period_id)',
        'This class already has a lesson in that period.',
    )

    @api.constrains('class_id', 'teacher_id', 'weekday', 'period_id')
    def _check_teacher_clash(self):
        # Only timetables of the same academic year can clash; last year's entries stay as history.
        for rec in self.filtered('teacher_id'):
            if self.search_count([
                    ('weekday', '=', rec.weekday), ('period_id', '=', rec.period_id.id),
                    ('teacher_id', '=', rec.teacher_id.id), ('year_id', '=', rec.year_id.id),
                    ('id', '!=', rec.id)]):
                raise ValidationError(self.env._(
                    '%s is already teaching another class in that period.', rec.teacher_id.name))

    # ------------------------------------------------------------------
    # Weekly grid (client action school_management.timetable_grid)
    # ------------------------------------------------------------------
    def action_open_timetable_grid(self):
        return self.env['ir.actions.actions']._for_xml_id('school_management.action_school_timetable_grid')

    @api.model
    def get_timetable_grid(self, mode='class', res_id=False, year_id=False):
        """Everything the weekly grid needs for one class or one teacher.

        :param mode: 'class' or 'teacher'
        :param res_id: id of the class or employee; the first one with lessons when empty
        :param year_id: academic year (teacher mode); defaults to the open year
        """
        Year = self.env['school.academic.year']
        Class = self.env['school.class']
        year = Year.browse(year_id).exists() if year_id else Year.search(
            [('state', '=', 'open')], order='date_start desc', limit=1)
        if not year:
            year = Year.search([], order='date_start desc', limit=1)

        classes = Class.search([('year_id', '=', year.id)]) if year else Class
        classes = classes.sorted(lambda c: (c.level_id.sequence, c.level_id.id, c.name or ''))
        year_entries = self.search([('year_id', '=', year.id)]) if year else self
        teachers = self.env['hr.employee'].sudo().search([('is_teacher', '=', True)], order='name')

        if mode == 'teacher':
            current = teachers.browse(res_id) if res_id in teachers.ids else (
                year_entries.teacher_id.sudo().sorted('name')[:1] or teachers[:1])
            entries = year_entries.filtered(lambda e: e.teacher_id.id == current.id)
            current_name = current.sudo().name
        else:
            current = Class.browse(res_id) if res_id in classes.ids else (
                classes.filtered(lambda c: c in year_entries.class_id)[:1] or classes[:1])
            entries = year_entries.filtered(lambda e: e.class_id == current)
            current_name = current.name

        periods = self.env['school.period'].search([])
        return {
            'mode': mode,
            'can_edit': self.has_access('create'),
            'year': {'id': year.id, 'name': year.name} if year else False,
            'years': [{'id': y.id, 'name': y.name} for y in Year.search([], order='date_start desc', limit=10)],
            'current': {'id': current.id, 'name': current_name or ''} if current else False,
            'classes': [{'id': c.id, 'name': c.name} for c in classes],
            'teachers': [{'id': t.id, 'name': t.name} for t in teachers],
            'weekdays': [{'key': key, 'name': name} for key, name in self._fields['weekday']._description_selection(self.env)],
            'periods': [{
                'id': p.id,
                'name': p.name,
                'start': p.start_time,
                'end': p.end_time,
                'is_break': p.is_break,
            } for p in periods],
            'entries': [{
                'id': e.id,
                'weekday': e.weekday,
                'period_id': e.period_id.id,
                'subject_id': e.subject_id.id,
                'subject': e.subject_id.name,
                'subject_code': e.subject_id.code or '',
                'teacher': e.teacher_id.sudo().name or '',
                'class': e.class_id.name or '',
                'room': e.room or e.class_id.room or '',
            } for e in entries],
        }


class SchoolTimetableReport(models.AbstractModel):
    # Printed from the weekly grid; the class or teacher and the year come in `data`, not as docids.
    _name = 'report.school_management.report_timetable'
    _description = 'Timetable Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        data = data or {}
        grid = self.env['school.timetable.entry'].get_timetable_grid(
            mode=data.get('mode') or 'class',
            res_id=data.get('res_id') or False,
            year_id=data.get('year_id') or False,
        )
        cells = {(e['weekday'], e['period_id']): e for e in grid['entries']}

        def hhmm(value):
            hours, minutes = divmod(round(value * 60), 60)
            return '%02d:%02d' % (hours, minutes)

        rows = [{
            'name': period['name'],
            'time': '%s - %s' % (hhmm(period['start']), hhmm(period['end'])),
            'is_break': period['is_break'],
            'cells': [cells.get((day['key'], period['id'])) for day in grid['weekdays']],
        } for period in grid['periods']]
        return {
            'doc_ids': [],
            'doc_model': 'school.timetable.entry',
            'docs': self.env['school.timetable.entry'],
            'grid': grid,
            'rows': rows,
            'company': self.env.company,
        }
