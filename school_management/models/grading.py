from odoo import api, fields, models
from odoo.exceptions import ValidationError


class SchoolGradeScale(models.Model):
    _name = 'school.grade.scale'
    _description = 'Grade Scale'
    _order = 'education_system, id'

    name = fields.Char(required=True, help='For example "CBC Performance Levels" or "KCSE Grading".')
    education_system = fields.Selection(
        [('cbc', 'CBC'), ('844', '8-4-4')], required=True, default='cbc',
        help='Classes of this education system are graded with this scale. Only one scale per system can be '
             'active; archive the old one before activating another.')
    line_ids = fields.One2many('school.grade.scale.line', 'scale_id', string='Bands',
                               help='Each band gives a grade to every percentage from its "From (%)" up to the '
                                    'next band. Editing bands applies to marks entered or recomputed afterwards.')
    active = fields.Boolean(default=True)

    @api.constrains('education_system', 'active')
    def _check_single_active(self):
        for rec in self.filtered('active'):
            if self.search_count([('education_system', '=', rec.education_system),
                                  ('id', '!=', rec.id)]):
                raise ValidationError(self.env._(
                    'Only one active grade scale is allowed per education system. '
                    'Archive the other scale first.'))

    @api.model
    def _get_scale(self, education_system):
        return self.sudo().search([('education_system', '=', education_system)], limit=1)

    def _band(self, percentage):
        """Return the band of this scale matching a percentage (empty if there is no scale)."""
        bands = self[:1].line_ids.sorted('min_mark', reverse=True)
        return bands.filtered(lambda l: l.min_mark <= (percentage or 0.0))[:1]

    @api.model
    def _get_line(self, education_system, percentage):
        """Return the band matching a percentage for the given education system."""
        return self._get_scale(education_system)._band(percentage)


class SchoolGradeScaleLine(models.Model):
    _name = 'school.grade.scale.line'
    _description = 'Grade Scale Band'
    _order = 'min_mark desc'

    scale_id = fields.Many2one('school.grade.scale', required=True, ondelete='cascade')
    grade = fields.Char(required=True, help='For example EE1, ME2, A- or B+.')
    min_mark = fields.Float(string='From (%)', required=True,
                            help='Lowest percentage that earns this grade.')
    points = fields.Integer(help='Points for this grade, summed on report cards (e.g. 12 for A in KCSE, 8 for EE1 in CBC).')
    descriptor = fields.Char(help='Meaning printed next to the grade, e.g. "Meets Expectations".')
