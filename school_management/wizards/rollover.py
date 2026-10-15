from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command


class SchoolRolloverWizard(models.TransientModel):
    _name = 'school.rollover.wizard'
    _description = 'Year-End Rollover'

    from_year_id = fields.Many2one(
        'school.academic.year', string='From Year', required=True,
        default=lambda self: self.env['school.academic.year'].search(
            [('state', '=', 'open')], order='date_start desc', limit=1),
        help='The year that is ending. All its classes are listed below.')
    to_year_id = fields.Many2one(
        'school.academic.year', string='To Year', required=True,
        compute='_compute_to_year_id', store=True, readonly=False,
        domain="[('id', '!=', from_year_id)]",
        help='The new year students move into. Create it under Configuration > Academic Years first.')
    copy_subjects = fields.Boolean(
        string='Copy subjects and teachers to new classes', default=True,
        help="A class created for the new year takes its subjects and subject teachers from "
             "this year's class of the same level and stream.")
    archive_old_classes = fields.Boolean(
        string="Archive last year's classes", default=True,
        help='Archived classes keep their history (report cards, attendance, invoices) but no '
             'longer appear in class pickers.')
    switch_years = fields.Boolean(
        string='Close the old year and open the new one', default=True,
        help='The open year is the default for new classes and admissions.')
    line_ids = fields.One2many(
        'school.rollover.wizard.line', 'wizard_id', string='Classes',
        compute='_compute_line_ids', store=True, readonly=False)
    state = fields.Selection([('draft', 'Draft'), ('done', 'Done')], default='draft')
    summary = fields.Text(readonly=True)

    @api.depends('from_year_id')
    def _compute_to_year_id(self):
        Year = self.env['school.academic.year']
        for wiz in self:
            wiz.to_year_id = Year.search(
                [('date_start', '>', wiz.from_year_id.date_start)], order='date_start', limit=1,
            ) if wiz.from_year_id else False

    @api.depends('from_year_id')
    def _compute_line_ids(self):
        Class = self.env['school.class']
        for wiz in self:
            commands = [Command.clear()]
            classes = Class.search([('year_id', '=', wiz.from_year_id.id)]) if wiz.from_year_id else Class
            for school_class in classes.sorted(lambda c: (c.level_id.sequence, c.level_id.id, c.name or '')):
                count = len(school_class.student_ids.filtered(lambda s: s.state == 'enrolled'))
                next_level = school_class.level_id.next_level_id
                if not count:
                    action = 'skip'
                elif next_level:
                    action = 'promote'
                else:
                    action = 'graduate'
                commands.append(Command.create({
                    'source_class_id': school_class.id,
                    'student_count': count,
                    'action': action,
                    'target_level_id': next_level.id,
                    'target_stream': school_class.stream,
                }))
            wiz.line_ids = commands

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------
    def _find_class(self, level, stream):
        """Class of the target year at this level and stream (streams compared loosely)."""
        if not level or not self.to_year_id:
            return self.env['school.class']
        key = (stream or '').strip().lower()
        return self.env['school.class'].search([
            ('year_id', '=', self.to_year_id.id), ('level_id', '=', level.id),
        ]).filtered(lambda c: (c.stream or '').strip().lower() == key)[:1]

    def _template_class(self, level, stream):
        """This year's class whose setup (subjects, capacity) a new class should copy."""
        candidates = self.env['school.class'].search([
            ('year_id', '=', self.from_year_id.id), ('level_id', '=', level.id)])
        key = (stream or '').strip().lower()
        return candidates.filtered(lambda c: (c.stream or '').strip().lower() == key)[:1] or candidates[:1]

    def _get_or_create_class(self, level, stream, created):
        target = self._find_class(level, stream) or created.get((level.id, (stream or '').strip().lower()))
        if target:
            return target
        template = self._template_class(level, stream)
        vals = {
            'level_id': level.id,
            'stream': stream or False,
            'year_id': self.to_year_id.id,
            'capacity': template.capacity if template else 40,
            'room': template.room if template else False,
            'company_id': (template.company_id or self.env.company).id,
        }
        if self.copy_subjects and template:
            vals['subject_line_ids'] = [Command.create({
                'subject_id': line.subject_id.id,
                'teacher_id': line.teacher_id.id,
                'periods_per_week': line.periods_per_week,
            }) for line in template.subject_line_ids]
        target = self.env['school.class'].create(vals)
        created[(level.id, (stream or '').strip().lower())] = target
        return target

    def action_apply(self):
        self.ensure_one()
        if self.from_year_id == self.to_year_id:
            raise UserError(self.env._('Choose two different academic years.'))
        if self.to_year_id.date_start <= self.from_year_id.date_start:
            raise UserError(self.env._('%(new)s must start after %(old)s.',
                                       new=self.to_year_id.name, old=self.from_year_id.name))
        lines = self.line_ids.filtered(lambda l: l.action != 'skip')
        if not lines:
            raise UserError(self.env._('There is nothing to roll over: every class is set to Skip.'))
        for line in lines.filtered(lambda l: l.action == 'promote' and not l.target_level_id):
            raise UserError(self.env._(
                'Choose the level %s is promoted to, or set it to Graduate.', line.source_class_id.name))

        # Work out every move before writing anything: moving students changes class rolls.
        created, moves = {}, []
        graduates = self.env['school.student']
        promoted = repeated = 0
        for line in lines:
            source = line.source_class_id
            students = source.student_ids.filtered(lambda s: s.state == 'enrolled')
            if not students:
                continue
            repeaters = line.repeater_ids & students
            movers = students - repeaters
            if line.action == 'promote' and movers:
                target = line.target_class_id or self._get_or_create_class(
                    line.target_level_id, line.target_stream, created)
                moves.append((movers, target))
                promoted += len(movers)
            elif line.action == 'graduate':
                graduates |= movers
            if repeaters:
                moves.append((repeaters, self._get_or_create_class(source.level_id, source.stream, created)))
                repeated += len(repeaters)

        graduates.action_graduate()
        for students, target in moves:
            students.write({'class_id': target.id})

        old_classes = self.line_ids.source_class_id
        if self.archive_old_classes:
            old_classes.write({'active': False})
        if self.switch_years:
            self.from_year_id.action_close()
            self.to_year_id.action_open()

        summary = [
            self.env._('%(n)s student(s) promoted.', n=promoted),
            self.env._('%(n)s student(s) graduated.', n=len(graduates)),
            self.env._('%(n)s student(s) repeating their grade.', n=repeated),
            self.env._('%(n)s class(es) created for %(year)s: %(names)s',
                       n=len(created), year=self.to_year_id.name,
                       names=', '.join(c.name for c in created.values()) or '-'),
        ]
        if self.archive_old_classes:
            summary.append(self.env._("%(n)s class(es) of %(year)s archived.",
                                      n=len(old_classes), year=self.from_year_id.name))
        if self.switch_years:
            summary.append(self.env._('%(old)s closed, %(new)s opened.',
                                      old=self.from_year_id.name, new=self.to_year_id.name))
        self.write({'state': 'done', 'summary': '\n'.join(summary)})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_view_new_classes(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Classes %s', self.to_year_id.name),
            'res_model': 'school.class',
            'view_mode': 'list,form',
            'domain': [('year_id', '=', self.to_year_id.id)],
            'context': {'default_year_id': self.to_year_id.id},
        }


class SchoolRolloverWizardLine(models.TransientModel):
    _name = 'school.rollover.wizard.line'
    _description = 'Year-End Rollover Class'
    _order = 'id'

    wizard_id = fields.Many2one('school.rollover.wizard', required=True, ondelete='cascade')
    to_year_id = fields.Many2one(related='wizard_id.to_year_id')
    source_class_id = fields.Many2one('school.class', string='Class', required=True)
    source_level_id = fields.Many2one(related='source_class_id.level_id', string='Level')
    student_count = fields.Integer(string='Students', help='Enrolled students in the class now.')
    action = fields.Selection(
        [('promote', 'Promote'), ('graduate', 'Graduate'), ('skip', 'Skip')],
        required=True, default='promote',
        help='Promote: move the students to the next level. Graduate: mark them graduated (final level). '
             'Skip: leave the class untouched.')
    target_level_id = fields.Many2one('school.grade.level', string='To Level',
                                      help='Level the class moves up to; suggested from the level\'s "Promotes To".')
    target_stream = fields.Char(string='To Stream',
                                help='Stream of the new class, the same as now by default. Change it to merge or '
                                     'rename streams.')
    target_class_id = fields.Many2one(
        'school.class', string='To Class', compute='_compute_target_class_id', store=True, readonly=False,
        domain="[('year_id', '=', to_year_id), ('level_id', '=', target_level_id)]",
        help='Existing class of the new year at the target level and stream. Leave empty to have it created.')
    creates_class = fields.Boolean(string='New Class', compute='_compute_creates_class',
                                   help='Ticked when the target class does not exist yet and will be created.')
    repeater_ids = fields.Many2many(
        'school.student', 'school_rollover_line_repeater_rel', 'line_id', 'student_id',
        string='Repeaters', domain="[('class_id', '=', source_class_id), ('state', '=', 'enrolled')]",
        help='Students who repeat the grade: they move to the same level and stream in the new year instead.')

    @api.depends('action', 'target_level_id', 'target_stream', 'wizard_id.to_year_id')
    def _compute_target_class_id(self):
        for line in self:
            line.target_class_id = line.wizard_id._find_class(
                line.target_level_id, line.target_stream) if line.action == 'promote' else False

    @api.depends('action', 'target_class_id', 'student_count', 'repeater_ids')
    def _compute_creates_class(self):
        for line in self:
            line.creates_class = (line.action == 'promote' and not line.target_class_id
                                  and line.student_count > len(line.repeater_ids))
