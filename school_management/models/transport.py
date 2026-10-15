from odoo import api, fields, models
from odoo.exceptions import ValidationError


class SchoolVehicle(models.Model):
    _name = 'school.vehicle'
    _description = 'School Vehicle'
    _order = 'name'

    name = fields.Char(required=True, help='Fleet name, for example Bus 1.')
    plate = fields.Char(string='Registration Plate', required=True, help='Number plate, e.g. KCA 123A.')
    capacity = fields.Integer(string='Seats', default=33,
                              help='Passenger seats. A route cannot have more active subscriptions than its '
                                   'vehicle has seats.')
    driver_id = fields.Many2one('hr.employee', string='Driver', domain="[('is_school_staff', '=', True)]",
                                help='Usual driver. Only employees with a school role are listed.')
    insurance_expiry = fields.Date(help='Date the motor insurance expires.')
    inspection_expiry = fields.Date(string='NTSA Inspection Expiry',
                                    help='Date the NTSA motor vehicle inspection certificate expires.')
    active = fields.Boolean(default=True)


class SchoolTransportRoute(models.Model):
    _name = 'school.transport.route'
    _description = 'Transport Route'
    _order = 'name'

    name = fields.Char(required=True, help='For example "Thika Road - Morning".')
    vehicle_id = fields.Many2one('school.vehicle', string='Vehicle',
                                 help='Vehicle serving the route; its seats limit the number of subscribers.')
    fee_per_term = fields.Monetary(currency_field='currency_id',
                                   help='Transport fee added to each subscribed student\'s term invoice when '
                                        '"Add transport fee" is ticked in Generate Invoices. The student\'s '
                                        'bursary discount also applies.')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    stop_ids = fields.One2many('school.transport.stop', 'route_id', string='Stops',
                               help='Pick-up points in the order the vehicle reaches them.')
    subscription_ids = fields.One2many('school.transport.subscription', 'route_id')
    capacity = fields.Integer(related='vehicle_id.capacity')
    seats_taken = fields.Integer(compute='_compute_seats', help='Number of active subscriptions on the route.')
    active = fields.Boolean(default=True)

    @api.depends('subscription_ids.state')
    def _compute_seats(self):
        for rec in self:
            rec.seats_taken = len(rec.subscription_ids.filtered(lambda s: s.state == 'active'))


class SchoolTransportStop(models.Model):
    _name = 'school.transport.stop'
    _description = 'Transport Stop'
    _order = 'route_id, sequence'

    route_id = fields.Many2one('school.transport.route', required=True, ondelete='cascade')
    name = fields.Char(required=True, help='Name of the pick-up point, e.g. "Total petrol station".')
    sequence = fields.Integer(default=10)
    pickup_time = fields.Float(help='Morning pick-up time at this stop, e.g. 06:30.')


class SchoolTransportSubscription(models.Model):
    _name = 'school.transport.subscription'
    _description = 'Transport Subscription'
    _order = 'id desc'

    student_id = fields.Many2one(
        'school.student', required=True,
        domain="[('student_type', '=', 'day'), ('state', '=', 'enrolled')]",
        help='Only enrolled day scholars are listed: boarders do not use school transport.')
    route_id = fields.Many2one('school.transport.route', string='Route', required=True,
                               help='Route the student travels on. Refused when the route\'s vehicle is full.')
    stop_id = fields.Many2one('school.transport.stop', string='Stop',
                              domain="[('route_id', '=', route_id)]",
                              help='Where the student is picked up. Only stops of the chosen route are listed.')
    date_from = fields.Date(default=fields.Date.context_today, help='First day the student uses the route.')
    date_to = fields.Date(help='Last day; filled in when the subscription is ended.')
    state = fields.Selection(
        [('active', 'Active'), ('ended', 'Ended')], default='active', required=True,
        help='Active subscriptions take a seat and are charged the route fee on term invoices.')

    @api.constrains('route_id', 'state')
    def _check_capacity(self):
        for rec in self:
            if rec.state == 'active' and rec.route_id.capacity and \
                    rec.route_id.seats_taken > rec.route_id.capacity:
                raise ValidationError(self.env._('Route %s has no free seats.', rec.route_id.name))

    @api.constrains('student_id', 'state')
    def _check_day_scholar(self):
        for rec in self.filtered(lambda s: s.state == 'active'):
            if rec.student_id.student_type != 'day':
                raise ValidationError(self.env._(
                    '%s is a boarder. Only day scholars can be subscribed to school transport.',
                    rec.student_id.name))

    def action_end(self):
        self.write({'state': 'ended', 'date_to': fields.Date.context_today(self)})
