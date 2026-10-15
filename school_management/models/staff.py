from odoo import api, fields, models

STAFF_TYPES = [('teaching', 'Teaching Staff'), ('support', 'Non-Teaching Staff')]


class SchoolStaffRole(models.Model):
    _name = 'school.staff.role'
    _description = 'School Staff Role'
    _order = 'staff_type, sequence, name'

    name = fields.Char(required=True, translate=True, help='Job role at the school, for example "Matron" or "Driver".')
    sequence = fields.Integer(default=10)
    staff_type = fields.Selection(STAFF_TYPES, required=True, default='support',
                                  help='Teaching staff can be class and subject teachers and appear on the '
                                       'timetable. Non-teaching staff are support roles such as librarian, '
                                       'matron, driver or cook.')
    employee_ids = fields.One2many('hr.employee', 'school_role_id', string='Staff')
    employee_count = fields.Integer(compute='_compute_employee_count', string='Staff Count',
                                    help='Number of staff members with this role.')
    active = fields.Boolean(default=True)

    _name_uniq = models.Constraint('UNIQUE (name)', 'This staff role already exists.')

    @api.depends('employee_ids')
    def _compute_employee_count(self):
        for role in self:
            role.employee_count = len(role.employee_ids)


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    school_role_id = fields.Many2one(
        'school.staff.role', string='School Role', index=True, tracking=True,
        help='The person\'s role at the school. A teaching role makes them selectable as class or subject '
             'teacher. Roles are managed under Configuration > Staff Roles. This does not give a login: '
             'system access is set on the user in Settings > Users.')
    school_staff_type = fields.Selection(
        related='school_role_id.staff_type', store=True, string='Staff Category')
    is_school_staff = fields.Boolean(
        compute='_compute_is_school_staff', store=True, string='School Staff',
        help='Has a school role; school staff pickers (warden, driver, library borrower) only list these employees.')
    is_teacher = fields.Boolean(
        compute='_compute_is_teacher', store=True, readonly=False, string='Teacher',
        help='Teaching staff can be class teachers, subject teachers and appear on the timetable.')
    tsc_number = fields.Char(string='TSC Number', help='Teachers Service Commission registration number.')
    teaching_subject_ids = fields.Many2many(
        'school.subject', 'school_teacher_subject_rel', 'employee_id', 'subject_id',
        string='Teaching Subjects', help='Subjects the teacher is qualified to teach.')
    taught_class_ids = fields.One2many('school.class', 'class_teacher_id', string='Classes as Class Teacher',
                                       help='Classes where this teacher is the class teacher.')

    @api.depends('school_role_id.staff_type')
    def _compute_is_teacher(self):
        # The role decides; without a role the value is kept as set by hand.
        for employee in self:
            if employee.school_role_id:
                employee.is_teacher = employee.school_role_id.staff_type == 'teaching'
            else:
                employee.is_teacher = employee.is_teacher

    @api.depends('school_role_id', 'is_teacher')
    def _compute_is_school_staff(self):
        for employee in self:
            employee.is_school_staff = bool(employee.school_role_id) or employee.is_teacher

    @api.model
    def _school_assign_teacher_role(self):
        """Give the default Teacher role to teachers created before staff roles existed."""
        role = self.env.ref('school_management.staff_role_teacher', raise_if_not_found=False)
        if role:
            self.sudo().with_context(active_test=False).search(
                [('is_teacher', '=', True), ('school_role_id', '=', False)]
            ).write({'school_role_id': role.id})


class HrEmployeePublic(models.Model):
    # Since Odoo 17, users without HR rights search hr.employee through hr.employee.public.
    # Stored fields declared here are added to its SQL view, so domains such as
    # [('is_teacher', '=', True)] keep working for teachers, registrars and librarians.
    _inherit = 'hr.employee.public'

    school_role_id = fields.Many2one('school.staff.role', string='School Role', readonly=True)
    school_staff_type = fields.Selection(STAFF_TYPES, string='Staff Category', readonly=True)
    is_school_staff = fields.Boolean(string='School Staff', readonly=True)
    is_teacher = fields.Boolean(string='Teacher', readonly=True)
    tsc_number = fields.Char(string='TSC Number', readonly=True)
