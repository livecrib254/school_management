from odoo import api, fields, models
from odoo.exceptions import UserError


class SchoolPromoteWizard(models.TransientModel):
    _name = 'school.promote.wizard'
    _description = 'Promote Students'

    class_id = fields.Many2one('school.class', string='From Class', required=True,
                               help='Class the students are in now. Its enrolled students are listed below.')
    action_type = fields.Selection(
        [('promote', 'Promote to another class'), ('graduate', 'Mark as graduated')],
        default='promote', required=True,
        help='Promote moves the students to another class (recorded in their class history). Graduate marks '
             'them as graduated: they stop counting as enrolled.')
    target_class_id = fields.Many2one('school.class', string='To Class',
                                      help='Class to move the students into. It must already exist; its capacity '
                                           'is enforced. For a whole school, use Year-End Rollover instead.')
    student_ids = fields.Many2many(
        'school.student', compute='_compute_students', store=True, readonly=False,
        string='Students', help='Students to move. Remove repeaters before applying.')

    @api.depends('class_id')
    def _compute_students(self):
        for rec in self:
            rec.student_ids = rec.class_id.student_ids.filtered(lambda s: s.state == 'enrolled')

    def action_apply(self):
        self.ensure_one()
        if not self.student_ids:
            raise UserError(self.env._('Select at least one student.'))
        if self.action_type == 'graduate':
            self.student_ids.action_graduate()
        else:
            if not self.target_class_id:
                raise UserError(self.env._('Choose the class students are promoted to.'))
            if self.target_class_id == self.class_id:
                raise UserError(self.env._('Students are already in %s.', self.class_id.name))
            self.student_ids.write({'class_id': self.target_class_id.id})
        return {'type': 'ir.actions.act_window_close'}
