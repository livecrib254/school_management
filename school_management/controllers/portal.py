from odoo import http
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal


class SchoolPortal(CustomerPortal):

    def _guardian_students(self):
        partner = request.env.user.partner_id
        return request.env['school.student'].sudo().search(
            [('guardian_ids.partner_id', '=', partner.id)])

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'school_children_count' in counters:
            values['school_children_count'] = len(self._guardian_students())
        if 'school_announcement_count' in counters:
            values['school_announcement_count'] = len(self._guardian_announcements())
        if 'school_message_count' in counters:
            values['school_message_count'] = len(self._guardian_messages())
        return values

    def _guardian_announcements(self, limit=None):
        students = self._guardian_students().filtered(lambda s: s.state == 'enrolled')
        Announcement = request.env['school.announcement'].sudo()
        if not students:
            return Announcement
        return Announcement.search(Announcement._portal_domain(students), limit=limit)

    def _guardian_messages(self):
        return request.env['school.guardian.message'].sudo().search([
            ('partner_id', '=', request.env.user.partner_id.id), ('state', '!=', 'draft')])

    @http.route('/my/children', type='http', auth='user', website=True)
    def my_children(self, **kw):
        students = self._guardian_students()
        cards = request.env['school.report.card'].sudo().search(
            [('student_id', 'in', students.ids), ('state', '=', 'published')])
        values = self._prepare_portal_layout_values()
        company = students[:1].company_id or request.env.company
        values.update({
            'students': students,
            'cards': cards,
            'announcements': self._guardian_announcements(limit=5),
            'partner': request.env.user.partner_id,
            'page_name': 'children',
            'school_name': company.sudo().school_name,
        })
        return request.render('school_management.portal_my_children', values)

    @http.route('/my/children/report/<int:card_id>', type='http', auth='user', website=True)
    def my_report_card(self, card_id, **kw):
        card = request.env['school.report.card'].sudo().search([
            ('id', '=', card_id),
            ('state', '=', 'published'),
            ('student_id', 'in', self._guardian_students().ids),
        ], limit=1)
        if not card:
            return request.redirect('/my')
        return self._show_report(
            model=card, report_type='pdf',
            report_ref='school_management.action_report_card', download=True)

    @http.route('/my/children/statement/<int:student_id>', type='http', auth='user', website=True)
    def my_fee_statement(self, student_id, **kw):
        student = self._guardian_students().filtered(lambda s: s.id == student_id)
        if not student:
            return request.redirect('/my')
        return self._show_report(
            model=student, report_type='pdf',
            report_ref='school_management.action_report_fee_statement', download=True)

    # ------------------------------------------------------------------
    # Announcements and messages
    # ------------------------------------------------------------------
    @http.route('/my/announcements', type='http', auth='user', website=True)
    def my_announcements(self, **kw):
        values = self._prepare_portal_layout_values()
        values.update({
            'announcements': self._guardian_announcements(),
            'partner': request.env.user.partner_id,
            'page_name': 'announcements',
        })
        return request.render('school_management.portal_my_announcements', values)

    @http.route('/my/announcements/<int:announcement_id>', type='http', auth='user', website=True)
    def my_announcement(self, announcement_id, **kw):
        announcement = self._guardian_announcements().filtered(lambda a: a.id == announcement_id)
        if not announcement:
            return request.redirect('/my/announcements')
        partner = request.env.user.partner_id
        if partner not in announcement.read_partner_ids:
            announcement.write({'read_partner_ids': [(4, partner.id)]})
        values = self._prepare_portal_layout_values()
        values.update({'announcement': announcement, 'page_name': 'announcement'})
        return request.render('school_management.portal_my_announcement', values)

    @http.route('/my/announcements/<int:announcement_id>/file/<int:attachment_id>',
                type='http', auth='user', website=True)
    def my_announcement_file(self, announcement_id, attachment_id, download=False, **kw):
        announcement = self._guardian_announcements().filtered(lambda a: a.id == announcement_id)
        attachment = announcement.attachment_ids.filtered(lambda a: a.id == attachment_id)
        if not attachment:
            raise request.not_found()
        stream = request.env['ir.binary']._get_stream_from(attachment.sudo(), 'raw')
        return stream.get_response(as_attachment=bool(download))

    @http.route('/my/messages', type='http', auth='user', website=True)
    def my_messages(self, **kw):
        values = self._prepare_portal_layout_values()
        values.update({'conversations': self._guardian_messages(), 'page_name': 'messages'})
        return request.render('school_management.portal_my_messages', values)

    @http.route('/my/messages/<int:message_id>', type='http', auth='user', website=True)
    def my_message(self, message_id, **kw):
        conversation = self._guardian_messages().filtered(lambda m: m.id == message_id)
        if not conversation:
            return request.redirect('/my/messages')
        values = self._prepare_portal_layout_values()
        # The access token lets the guardian reply in the portal chatter without rights on the model.
        values = self._get_page_view_values(
            conversation, conversation._portal_ensure_token(), values, 'my_school_messages_history', False)
        values.update({
            'conversation': conversation,
            'page_name': 'message',
            'disable_composer': conversation.state != 'open',
        })
        return request.render('school_management.portal_my_message', values)
