from odoo import fields, models
from odoo.exceptions import UserError


class SchoolFeeGenerateWizard(models.TransientModel):
    _name = 'school.fee.generate.wizard'
    _description = 'Generate Fee Invoices'

    term_id = fields.Many2one(
        'school.term', string='Term', required=True,
        default=lambda self: self.env['school.term']._get_current(),
        help='Term being billed. Students already invoiced for this term are skipped, so it is safe to run again '
             'for late admissions.')
    class_ids = fields.Many2many('school.class', string='Classes', required=True,
                                 help='Every enrolled student of these classes gets an invoice from the fee '
                                      'structure matching their grade level and day/boarder status.')
    invoice_date = fields.Date(default=fields.Date.context_today, required=True, help='Date printed on the invoices.')
    due_date = fields.Date(help='Date fees must be paid by. Leave empty to use the payment terms of the guardian.')
    include_transport = fields.Boolean(
        string='Add transport fee for subscribed students', default=True,
        help='Adds the route\'s fee per term for students with an active transport subscription.')
    post_invoices = fields.Boolean(
        string='Post invoices immediately',
        help='Posted invoices count in fee balances and can be paid and sent to parents. Leave unticked to '
             'review the drafts first, then post them from Student Invoices.')
    state = fields.Selection([('draft', 'Draft'), ('done', 'Done')], default='draft')
    summary = fields.Text(readonly=True)
    move_ids = fields.Many2many('account.move', string='Invoices', readonly=True)

    def _find_structure(self, student):
        domain = [
            ('level_ids', 'in', student.level_id.id),
            ('year_id', 'in', [False, self.term_id.year_id.id]),
            ('term_id', 'in', [False, self.term_id.id]),
            ('student_type', 'in', ['all', student.student_type]),
        ]
        structures = self.env['school.fee.structure'].search(domain)
        return structures.sorted(
            key=lambda s: (bool(s.term_id), s.student_type != 'all', bool(s.year_id)),
            reverse=True)[:1]

    def action_generate(self):
        self.ensure_one()
        Move = self.env['account.move']
        transport_product = self.env.ref('school_management.product_fee_transport', raise_if_not_found=False)
        students = self.env['school.student'].search([
            ('class_id', 'in', self.class_ids.ids), ('state', '=', 'enrolled')])
        if not students:
            raise UserError(self.env._('There are no enrolled students in the selected classes.'))

        created, skipped, no_structure = Move, [], []
        for student in students:
            if Move.search_count([
                    ('student_id', '=', student.id), ('school_term_id', '=', self.term_id.id),
                    ('move_type', '=', 'out_invoice'), ('state', '!=', 'cancel')]):
                skipped.append(student.name)
                continue
            structure = self._find_structure(student)
            if not structure.line_ids:
                no_structure.append(student.name)
                continue
            discount = student.fee_discount_percent
            lines = [(0, 0, {
                'product_id': line.product_id.id,
                'name': line.description or line.product_id.name,
                'quantity': 1,
                'price_unit': line.amount,
                'discount': discount,
                'tax_ids': [(6, 0, [])],
            }) for line in structure.line_ids]
            if self.include_transport and transport_product:
                for sub in student.transport_subscription_ids.filtered(lambda s: s.state == 'active'):
                    if sub.route_id.fee_per_term:
                        lines.append((0, 0, {
                            'product_id': transport_product.id,
                            'name': self.env._('Transport - %s', sub.route_id.name),
                            'quantity': 1,
                            'price_unit': sub.route_id.fee_per_term,
                            'discount': discount,
                            'tax_ids': [(6, 0, [])],
                        }))
            created |= Move.create({
                'move_type': 'out_invoice',
                'partner_id': student.billing_partner_id.id,
                'student_id': student.id,
                'school_class_id': student.class_id.id,
                'school_term_id': self.term_id.id,
                'ref': '%s - %s' % (student.admission_no, self.term_id.display_name),
                'invoice_date': self.invoice_date,
                'invoice_date_due': self.due_date or False,
                'invoice_line_ids': lines,
            })
        if self.post_invoices and created:
            created.action_post()

        summary = [self.env._('%s invoice(s) created.', len(created))]
        if skipped:
            summary.append(self.env._('Already invoiced for this term (%(n)s): %(names)s',
                             n=len(skipped), names=', '.join(skipped)))
        if no_structure:
            summary.append(self.env._('No matching fee structure with fee items (%(n)s): %(names)s',
                             n=len(no_structure), names=', '.join(no_structure)))
        self.write({'state': 'done', 'summary': '\n'.join(summary), 'move_ids': [(6, 0, created.ids)]})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_view_invoices(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('account.action_move_out_invoice_type')
        action['domain'] = [('id', 'in', self.move_ids.ids)]
        action['context'] = {'default_move_type': 'out_invoice', 'school_invoice_list': True}
        return action
