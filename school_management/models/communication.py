from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class SchoolAnnouncement(models.Model):
    _name = 'school.announcement'
    _description = 'School Announcement'
    _order = 'is_pinned desc, date_publish desc, id desc'

    name = fields.Char(string='Title', required=True, help='Headline shown to parents on the portal.')
    body = fields.Html(string='Message', required=True, sanitize_style=True)
    attachment_ids = fields.Many2many(
        'ir.attachment', 'school_announcement_attachment_rel', 'announcement_id', 'attachment_id',
        string='Attachments',
        help='Files parents can download from the announcement (letters, circulars, fee schedules...). '
             'They are also attached to the email when the announcement is emailed.')
    audience = fields.Selection(
        [('all', 'All Parents'), ('level', 'Grade Levels'), ('class', 'Classes')],
        default='all', required=True,
        help='Which parents see the announcement: guardians of enrolled students in the whole school, '
             'in some grade levels, or in some classes.')
    level_ids = fields.Many2many('school.grade.level', string='Grade Levels')
    class_ids = fields.Many2many('school.class', string='Classes')
    date_publish = fields.Date(string='Publish On', default=fields.Date.context_today, required=True,
                               help='Parents see the announcement from this date.')
    date_expire = fields.Date(string='Show Until',
                              help='Hidden from parents after this date. Leave empty to keep it visible.')
    is_pinned = fields.Boolean(string='Important',
                               help='Shown first and highlighted on the parents\' page.')
    send_email = fields.Boolean(string='Also Send by Email',
                                help='Email the announcement to every guardian in the audience when it is published.')
    send_sms = fields.Boolean(string='Also Send by SMS',
                              help='Text the SMS message below to every guardian in the audience who has a phone '
                                   'number when the announcement is published.')
    sms_body = fields.Text(string='SMS Text',
                           help='Short text sent by SMS. 160 characters make one SMS; longer texts are sent as '
                                'several SMS and cost more.')
    state = fields.Selection([('draft', 'Draft'), ('published', 'Published')], default='draft', required=True)
    email_sent = fields.Boolean(readonly=True, copy=False,
                                help='The announcement was emailed already; republishing does not email it again.')
    sms_sent = fields.Boolean(string='SMS Sent', readonly=True, copy=False,
                              help='The SMS were queued already; republishing does not send them again.')
    sms_count = fields.Integer(string='SMS Queued', readonly=True, copy=False,
                               help='Number of guardians the SMS was queued for (distinct phone numbers).')
    user_id = fields.Many2one('res.users', string='Author', default=lambda self: self.env.user, readonly=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)
    read_partner_ids = fields.Many2many('res.partner', 'school_announcement_read_rel', 'announcement_id',
                                        'partner_id', string='Read By', readonly=True, copy=False)
    recipient_count = fields.Integer(compute='_compute_counts', string='Recipients',
                                     help='Guardians of enrolled students in the audience.')
    read_count = fields.Integer(compute='_compute_counts', string='Read',
                                help='Guardians who opened the announcement on the portal.')

    @api.depends('audience', 'level_ids', 'class_ids', 'read_partner_ids')
    def _compute_counts(self):
        for rec in self:
            rec.recipient_count = len(rec._recipient_partners())
            rec.read_count = len(rec.read_partner_ids)

    @api.constrains('audience', 'level_ids', 'class_ids')
    def _check_audience(self):
        for rec in self:
            if rec.audience == 'level' and not rec.level_ids:
                raise ValidationError(self.env._('Choose the grade levels the announcement is for.'))
            if rec.audience == 'class' and not rec.class_ids:
                raise ValidationError(self.env._('Choose the classes the announcement is for.'))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._link_attachments()
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'attachment_ids' in vals:
            self._link_attachments()
        return res

    def _link_attachments(self):
        # Files uploaded before the first save have no res_id; tie them to the announcement so
        # they follow its access rights and are not garbage-collected as orphans.
        for rec in self:
            rec.attachment_ids.filtered(lambda a: not a.res_id).sudo().write(
                {'res_model': self._name, 'res_id': rec.id})

    def _audience_students(self):
        self.ensure_one()
        domain = [('state', '=', 'enrolled'), ('company_id', 'in', [self.company_id.id, False])]
        if self.audience == 'level':
            domain.append(('level_id', 'in', self.level_ids.ids))
        elif self.audience == 'class':
            domain.append(('class_id', 'in', self.class_ids.ids))
        return self.env['school.student'].sudo().search(domain)

    def _recipient_partners(self):
        self.ensure_one()
        return self._audience_students().guardian_ids.partner_id

    @api.model
    def _portal_domain(self, students):
        """Published, current announcements addressed to any of these students' guardians."""
        today = fields.Date.context_today(self)
        return [
            ('state', '=', 'published'), ('date_publish', '<=', today),
            '|', ('date_expire', '=', False), ('date_expire', '>=', today),
            ('company_id', 'in', students.company_id.ids or self.env.company.ids),
            '|', '|', ('audience', '=', 'all'),
            '&', ('audience', '=', 'level'), ('level_ids', 'in', students.level_id.ids),
            '&', ('audience', '=', 'class'), ('class_ids', 'in', students.class_id.ids),
        ]

    def action_publish(self):
        for rec in self:
            if rec.state == 'published':
                continue
            rec.state = 'published'
            if rec.send_email and not rec.email_sent:
                rec._send_email()
                rec.email_sent = True
            if rec.send_sms and not rec.sms_sent:
                rec.sms_count = rec._send_sms()
                rec.sms_sent = True

    @api.onchange('send_sms')
    def _onchange_send_sms(self):
        if self.send_sms and not self.sms_body:
            school = self.company_id.school_name or self.company_id.name
            self.sms_body = self.env._('%(school)s: %(title)s. Details on the parent portal.',
                                       school=school, title=self.name or '')

    @api.constrains('send_sms', 'sms_body')
    def _check_sms_body(self):
        for rec in self:
            if rec.send_sms and not (rec.sms_body or '').strip():
                raise ValidationError(self.env._('Write the SMS text, or untick "Also Send by SMS".'))

    def _send_sms(self):
        """Queue one SMS per distinct guardian phone number; returns how many were queued."""
        self.ensure_one()
        to_send = {}
        # Numbers on the SMS blacklist (Settings > Technical > Phone / SMS) are skipped.
        for partner in self._recipient_partners().filtered(lambda p: not p.phone_sanitized_blacklisted):
            number = partner._phone_format(fname='phone')
            if number and number not in to_send:
                to_send[number] = partner
        if not to_send:
            return 0
        body = self.sms_body.strip()
        self.env['sms.sms'].sudo().create([
            {'number': number, 'body': body, 'partner_id': partner.id} for number, partner in to_send.items()])
        # Sent in the background by the SMS queue, in batches, through the company's SMS provider.
        self.env.ref('sms.ir_cron_sms_scheduler_action').sudo()._trigger()
        return len(to_send)

    def action_draft(self):
        self.write({'state': 'draft'})

    def _send_email(self):
        self.ensure_one()
        partners = self._recipient_partners().filtered('email')
        if not partners:
            return
        email_from = self.company_id.email_formatted or self.env.user.email_formatted
        self.env['mail.mail'].sudo().create([{
            'subject': self.name,
            'body_html': self.body,
            'email_from': email_from,
            'recipient_ids': [(4, partner.id)],
            'attachment_ids': [(6, 0, self.attachment_ids.ids)],
            'auto_delete': True,
        } for partner in partners])

    def action_view_readers(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Read By'),
            'res_model': 'res.partner',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.read_partner_ids.ids)],
        }


class SchoolGuardianMessage(models.Model):
    _name = 'school.guardian.message'
    _description = 'Message to Guardian'
    _inherit = ['portal.mixin', 'mail.thread']
    _order = 'write_date desc, id desc'

    name = fields.Char(string='Subject', required=True, tracking=True)
    level_id = fields.Many2one(
        'school.grade.level', string='Grade Level', index=True,
        help='Narrows the Class, Student and Guardian lists to this grade level.')
    class_id = fields.Many2one(
        'school.class', string='Class', index=True,
        domain="[('level_id', '=', level_id)] if level_id else []",
        help='Narrows the Student and Guardian lists to this class. Filled in from the student.')
    partner_id = fields.Many2one(
        'res.partner', string='Guardian', required=True, index=True, tracking=True,
        domain="[('is_school_guardian', '=', True)]"
               " + ([('guardian_line_ids.student_id', '=', student_id)] if student_id"
               " else [('guardian_line_ids.student_id.class_id', '=', class_id)] if class_id"
               " else [('guardian_line_ids.student_id.level_id', '=', level_id)] if level_id else [])",
        help='Parent or guardian the conversation is with. They read and reply on the parent portal and '
             'receive each message by email. Choosing the student first fills in their primary guardian.')
    student_id = fields.Many2one(
        'school.student', string='Student', index=True,
        domain="([('guardian_ids.partner_id', '=', partner_id)] if partner_id else [])"
               " + ([('class_id', '=', class_id)] if class_id"
               " else [('level_id', '=', level_id)] if level_id else [])",
        help='Child the message is about, if any. Search by name or admission number, or pick a grade '
             'level and class first to narrow the list.')
    body = fields.Html(string='Message', sanitize_style=True,
                       help='First message, sent to the guardian with "Send". Continue the conversation in the '
                            'chatter below; the guardian\'s replies appear there too.')
    state = fields.Selection(
        [('draft', 'Draft'), ('open', 'Open'), ('closed', 'Closed')], default='draft', required=True, tracking=True,
        help='Open: the guardian sees the conversation and can reply. Closed: still visible, replies are turned off.')
    user_id = fields.Many2one('res.users', string='From', default=lambda self: self.env.user, tracking=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)
    send_sms = fields.Boolean(
        string='Also Notify by SMS',
        help='When sending, also text the guardian that there is a new message, with a link to read and reply. '
             'The message itself stays on the portal and in the email.')

    def _compute_access_url(self):
        super()._compute_access_url()
        for rec in self:
            rec.access_url = '/my/messages/%s' % rec.id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('student_id') and not vals.get('class_id'):
                student = self.env['school.student'].browse(vals['student_id'])
                vals['class_id'] = student.class_id.id
                vals.setdefault('level_id', student.level_id.id)
        return super().create(vals_list)

    @api.onchange('level_id')
    def _onchange_level_id(self):
        if self.level_id and self.class_id.level_id != self.level_id:
            self.class_id = False
        if self.level_id and self.student_id and self.student_id.level_id != self.level_id:
            self.student_id = False

    @api.onchange('class_id')
    def _onchange_class_id(self):
        if self.class_id:
            self.level_id = self.class_id.level_id
            if self.student_id and self.student_id.class_id != self.class_id:
                self.student_id = False

    @api.onchange('student_id')
    def _onchange_student_id(self):
        student = self.student_id
        if not student:
            return
        if student.class_id:
            self.class_id = student.class_id
            self.level_id = student.level_id
        if self.partner_id not in student.guardian_ids.partner_id:
            self.partner_id = student.primary_guardian_id or student.guardian_ids[:1].partner_id

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        if self.student_id and self.partner_id not in self.student_id.guardian_ids.partner_id:
            self.student_id = False

    def action_send(self):
        for rec in self:
            if rec.state != 'draft':
                continue
            if not rec.body or rec.body == '<p><br></p>':
                raise UserError(self.env._('Write the message before sending it.'))
            # The guardian is notified of school messages; the sender of the guardian's replies.
            rec.message_subscribe(partner_ids=(rec.partner_id | rec.user_id.partner_id).ids)
            rec.message_post(
                body=rec.body,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
                partner_ids=rec.partner_id.ids,
            )
            rec.state = 'open'
            if rec.send_sms:
                rec._notify_guardian_sms()

    def _notify_guardian_sms(self):
        self.ensure_one()
        _ = self.env._
        school = self.company_id.school_name or self.company_id.name
        url = '%s/my/messages/%s' % (self.get_base_url(), self.id)
        if self.student_id:
            body = _('%(school)s: new message about %(student)s: "%(subject)s". Read and reply: %(url)s',
                     school=school, student=self.student_id.name, subject=self.name, url=url)
        else:
            body = _('%(school)s: new message: "%(subject)s". Read and reply: %(url)s',
                     school=school, subject=self.name, url=url)
        # Logged as an internal note with the SMS status (sent / error) on the conversation.
        self._message_sms(body, partner_ids=self.partner_id.ids)

    def action_close(self):
        self.write({'state': 'closed'})

    def action_reopen(self):
        self.write({'state': 'open'})

    def message_post(self, **kwargs):
        # The portal hides the reply box on closed conversations; refuse direct posts too.
        if self.env.user.share and any(rec.state != 'open' for rec in self):
            raise UserError(self.env._('This conversation is closed. Please contact the school office.'))
        return super().message_post(**kwargs)
