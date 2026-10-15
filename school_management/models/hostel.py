from odoo import api, fields, models
from odoo.exceptions import ValidationError


class SchoolHostel(models.Model):
    _name = 'school.hostel'
    _description = 'Hostel / Dormitory Block'
    _order = 'name'

    name = fields.Char(required=True, help='Name of the hostel or dormitory block, e.g. "Kilimanjaro House".')
    gender = fields.Selection(
        [('male', 'Boys'), ('female', 'Girls'), ('mixed', 'Mixed')], default='mixed', required=True,
        help='Boys\' or girls\' hostels only accept students of that gender; mixed hostels accept everyone.')
    warden_id = fields.Many2one('hr.employee', string='Warden / Matron', domain="[('is_school_staff', '=', True)]",
                                help='Staff member in charge of the hostel (matron, patron or warden).')
    room_ids = fields.One2many('school.hostel.room', 'hostel_id', string='Rooms',
                               help='Rooms or dormitories in this hostel and their number of beds.')
    total_beds = fields.Integer(compute='_compute_beds', help='Total beds across all rooms.')
    occupied_beds = fields.Integer(compute='_compute_beds', help='Beds with an active allocation.')
    active = fields.Boolean(default=True)

    @api.depends('room_ids.beds', 'room_ids.occupied')
    def _compute_beds(self):
        for rec in self:
            rec.total_beds = sum(rec.room_ids.mapped('beds'))
            rec.occupied_beds = sum(rec.room_ids.mapped('occupied'))


class SchoolHostelRoom(models.Model):
    _name = 'school.hostel.room'
    _description = 'Hostel Room / Dormitory'
    _order = 'hostel_id, name'

    name = fields.Char(string='Room / Dorm', required=True, help='Room or dormitory name or number.')
    hostel_id = fields.Many2one('school.hostel', required=True, ondelete='cascade', help='Hostel the room belongs to.')
    beds = fields.Integer(default=4, help='Number of beds. Allocations beyond this are refused.')
    allocation_ids = fields.One2many('school.hostel.allocation', 'room_id')
    occupied = fields.Integer(compute='_compute_occupied', help='Beds with an active allocation.')
    available = fields.Integer(compute='_compute_occupied', help='Free beds: beds minus occupied.')

    @api.depends('hostel_id.name', 'name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = '%s / %s' % (rec.hostel_id.name or '', rec.name or '')

    @api.depends('beds', 'allocation_ids.state')
    def _compute_occupied(self):
        for rec in self:
            rec.occupied = len(rec.allocation_ids.filtered(lambda a: a.state == 'active'))
            rec.available = rec.beds - rec.occupied


class SchoolHostelAllocation(models.Model):
    _name = 'school.hostel.allocation'
    _description = 'Hostel Allocation'
    _order = 'id desc'

    student_id = fields.Many2one(
        'school.student', required=True,
        domain="[('student_type', '=', 'boarding'), ('state', '=', 'enrolled')]",
        help='Only enrolled boarders are listed: day scholars are not given hostel beds. '
             'A student can only hold one active bed.')
    room_id = fields.Many2one('school.hostel.room', string='Room', required=True,
                              help='Room the student sleeps in. Refused when the room is full or the hostel is '
                                   'for the other gender.')
    hostel_id = fields.Many2one(related='room_id.hostel_id', store=True)
    date_from = fields.Date(default=fields.Date.context_today, help='Date the student moved in.')
    date_to = fields.Date(help='Date the student moved out; filled in when the allocation is ended.')
    state = fields.Selection(
        [('active', 'Active'), ('ended', 'Ended')], default='active', required=True,
        help='Active allocations occupy a bed. End the allocation when the student leaves the room.')

    @api.constrains('room_id', 'student_id', 'state')
    def _check_allocation(self):
        for rec in self:
            if rec.state != 'active':
                continue
            if rec.student_id.student_type != 'boarding':
                raise ValidationError(self.env._(
                    '%s is a day scholar. Only boarders can be allocated a hostel bed.',
                    rec.student_id.name))
            if rec.room_id.occupied > rec.room_id.beds:
                raise ValidationError(self.env._('Room %s is full.', rec.room_id.display_name))
            gender = rec.room_id.hostel_id.gender
            if gender != 'mixed' and rec.student_id.gender and rec.student_id.gender != gender:
                raise ValidationError(
                    self.env._('%(student)s cannot be placed in %(hostel)s.',
                      student=rec.student_id.name, hostel=rec.room_id.hostel_id.name))
            if self.search_count([('student_id', '=', rec.student_id.id),
                                  ('state', '=', 'active'), ('id', '!=', rec.id)]):
                raise ValidationError(self.env._('%s already has an active bed.', rec.student_id.name))

    def action_end(self):
        self.write({'state': 'ended', 'date_to': fields.Date.context_today(self)})
