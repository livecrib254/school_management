from odoo import fields, models
from odoo.exceptions import UserError


class SchoolReportCardWizard(models.TransientModel):
    _name = 'school.report.card.wizard'
    _description = 'Generate Report Cards'

    class_id = fields.Many2one('school.class', string='Class', required=True,
                               help='A report card is created or refreshed for every enrolled student of the class.')
    term_id = fields.Many2one(
        'school.term', string='Term', required=True,
        default=lambda self: self.env['school.term']._get_current(),
        help='Only exams of this term marked Done are used. Published cards are left unchanged.')

    def action_generate(self):
        self.ensure_one()
        students = self.class_id.student_ids.filtered(lambda s: s.state == 'enrolled')
        if not students:
            raise UserError(self.env._('There are no enrolled students in %s.', self.class_id.name))
        if not self.env['school.exam'].search_count([
                ('class_id', '=', self.class_id.id), ('term_id', '=', self.term_id.id),
                ('state', '=', 'done')], limit=1):
            raise UserError(self.env._(
                '%(cls)s has no completed exam in %(term)s. Report cards only use exams marked Done.',
                cls=self.class_id.name, term=self.term_id.display_name))
        Card = self.env['school.report.card']
        # A student who changed class during the term already has a card for it: move it.
        student_cards = Card.search([('student_id', 'in', students.ids), ('term_id', '=', self.term_id.id)])
        student_cards.filtered(
            lambda c: c.class_id != self.class_id and c.state == 'draft'
        ).write({'class_id': self.class_id.id})
        missing = students - student_cards.student_id
        if missing:
            Card.create([{
                'student_id': s.id,
                'class_id': self.class_id.id,
                'term_id': self.term_id.id,
            } for s in missing])
        cards = Card.search([('class_id', '=', self.class_id.id), ('term_id', '=', self.term_id.id)])
        cards.action_compute()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Report Cards'),
            'res_model': 'school.report.card',
            'view_mode': 'list,form',
            'domain': [('id', 'in', cards.ids)],
        }
