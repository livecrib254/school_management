from odoo import api, fields, models
from odoo.exceptions import UserError


class SchoolAdmission(models.Model):
    _name = 'school.admission'
    _description = 'Admission Application'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'application_date desc, id desc'

    name = fields.Char(string='Reference', readonly=True, copy=False, default='New',
                       help='Application number, assigned automatically (APP/year/number).')
    applicant_name = fields.Char(required=True, tracking=True,
                                 help='Full name of the child applying. Becomes the student\'s name on enrolment.')
    date_of_birth = fields.Date(help='Copied to the student record on enrolment.')
    gender = fields.Selection([('male', 'Male'), ('female', 'Female'), ('other', 'Other')],
                              help='Copied to the student record on enrolment.')
    level_id = fields.Many2one('school.grade.level', string='Applying For', required=True, tracking=True,
                               help='Grade or form the child is applying to join.')
    year_id = fields.Many2one(
        'school.academic.year', string='Academic Year',
        default=lambda self: self.env['school.academic.year'].search([('state', '=', 'open')], limit=1),
        help='Year the child would start. Defaults to the open year.')
    class_id = fields.Many2one('school.class', string='Allocated Class',
                               domain="[('level_id', '=', level_id)]",
                               help='Class the child will join. Required before "Enrol Student"; only classes '
                                    'of the level applied for are listed.')
    student_type = fields.Selection(
        [('day', 'Day Scholar'), ('boarding', 'Boarder')], default='day', required=True,
        help='Day scholar or boarder. Decides transport or hostel eligibility and the fee structure.')
    application_date = fields.Date(default=fields.Date.context_today, help='Date the application was received.')

    guardian_name = fields.Char(required=True,
                                help='Parent or guardian applying. A guardian contact is created on enrolment '
                                     'unless one already exists with the same National ID or email.')
    guardian_relation = fields.Selection([
        ('father', 'Father'), ('mother', 'Mother'), ('guardian', 'Guardian'), ('other', 'Other'),
    ], default='guardian', required=True, help='How the guardian is related to the child.')
    guardian_phone = fields.Char(help='Main phone number for the guardian.')
    guardian_email = fields.Char(help='Used for invoices and the parent portal. Also used to recognise an '
                                      'existing guardian (e.g. of a sibling).')
    guardian_national_id = fields.Char(string='Guardian National ID / Passport No.',
                                       help='Recognises a guardian who already has a child in the school, so '
                                            'siblings share one guardian record.')
    guardian_occupation = fields.Char(help='Occupation or employer of the guardian.')

    previous_school = fields.Char(help='School the child is coming from, if any.')
    previous_grade = fields.Char(help='Last grade or form completed at the previous school.')
    entry_test_score = fields.Float(string='Entry Assessment Score (%)',
                                    help='Result of the entry interview or assessment, if the school holds one.')
    notes = fields.Text(help='Interview notes, documents received, special requirements.')

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('review', 'Under Review'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
        ('enrolled', 'Enrolled'),
    ], default='draft', tracking=True, required=True,
        help='Draft → Submitted → Under Review → Accepted → Enrolled (the student record is created). '
             'Rejected applications can be reset to draft.')
    student_id = fields.Many2one('school.student', readonly=True, copy=False,
                                 help='Student record created when the application was enrolled.')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('school.admission') or 'New'
        return super().create(vals_list)

    def action_submit(self):
        self.write({'state': 'submitted'})

    def action_review(self):
        self.write({'state': 'review'})

    def action_accept(self):
        self.write({'state': 'accepted'})

    def action_reject(self):
        self.write({'state': 'rejected'})

    def action_reset(self):
        self.write({'state': 'draft'})

    def action_enroll(self):
        self.ensure_one()
        if self.state != 'accepted':
            raise UserError(self.env._('Only accepted applications can be enrolled.'))
        if not self.class_id:
            raise UserError(self.env._('Select the class to enrol the student into.'))
        Partner = self.env['res.partner']
        # Reuse an existing contact (e.g. a parent of a sibling): national ID first, then email.
        guardian = Partner.browse()
        if self.guardian_national_id:
            guardian = Partner.search(
                [('guardian_national_id', '=ilike', self.guardian_national_id.strip())], limit=1)
        if not guardian and self.guardian_email:
            guardian = Partner.search([('email', '=ilike', self.guardian_email.strip())], limit=1)
        if guardian:
            missing = {
                field: value for field, value in [
                    ('phone', self.guardian_phone),
                    ('guardian_national_id', self.guardian_national_id),
                    ('guardian_occupation', self.guardian_occupation),
                ] if value and not guardian[field]
            }
            guardian.write(dict(missing, is_school_guardian=True))
        else:
            guardian = Partner.create({
                'name': self.guardian_name,
                'phone': self.guardian_phone,
                'email': self.guardian_email,
                'guardian_national_id': self.guardian_national_id,
                'guardian_occupation': self.guardian_occupation,
                'is_school_guardian': True,
            })
        student = self.env['school.student'].create({
            'name': self.applicant_name,
            'gender': self.gender,
            'date_of_birth': self.date_of_birth,
            'class_id': self.class_id.id,
            'student_type': self.student_type,
            'previous_school': self.previous_school,
            'state': 'enrolled',
            'guardian_ids': [(0, 0, {
                'partner_id': guardian.id,
                'relation': self.guardian_relation,
                'is_primary': True,
                'is_fee_payer': True,
                'is_emergency': True,
            })],
        })
        self.write({'student_id': student.id, 'state': 'enrolled'})
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'school.student',
            'res_id': student.id,
            'view_mode': 'form',
        }

    def action_view_student(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'school.student',
            'res_id': self.student_id.id,
            'view_mode': 'form',
        }
