from datetime import timedelta

from odoo import api, fields, models


class SchoolDashboard(models.AbstractModel):
    """Aggregates for the School dashboard client action.

    Figures are read with sudo so every school role sees school-wide totals, but each
    section is only returned to the roles allowed to open the underlying records.
    """
    _name = 'school.dashboard'
    _description = 'School Dashboard'

    @api.model
    def get_dashboard_data(self, term_id=False):
        env = self.env
        user = env.user
        can = {
            'academics': user.has_group('school_management.group_school_teacher'),
            'records': user.has_group('school_management.group_school_registrar'),
            'fees': user.has_group('school_management.group_school_accountant'),
            'library': user.has_group('school_management.group_school_librarian'),
            'staff': user.has_group('school_management.group_school_manager'),
        }
        can['students'] = can['academics'] or can['records'] or can['fees']

        Term = env['school.term'].sudo()
        term = Term.browse(term_id).exists() if term_id else Term._get_current()
        if not term:
            term = Term.search([('date_start', '<=', fields.Date.context_today(self))],
                               order='date_start desc', limit=1)
        terms = Term.search([], order='date_start desc', limit=12)

        company_domain = ['|', ('company_id', '=', False), ('company_id', 'in', env.companies.ids)]
        students = env['school.student'].sudo().search(
            [('state', '=', 'enrolled')] + company_domain)
        company = env.company

        data = {
            'school_name': company.school_name or False,
            'can': can,
            'term': {'id': term.id, 'name': term.display_name} if term else False,
            'terms': [{'id': t.id, 'name': t.display_name} for t in terms],
            'currency': {
                'symbol': company.currency_id.symbol,
                'position': company.currency_id.position,
                'digits': company.currency_id.decimal_places,
            },
            'today': fields.Date.to_string(fields.Date.context_today(self)),
        }
        if can['students']:
            data.update(self._students_section(students))
        if can['academics']:
            data.update(self._academics_section(students, term))
        if can['records']:
            data.update(self._records_section())
        if can['fees']:
            data.update(self._fees_section(term))
        if can['library']:
            data.update(self._library_section())
        return data

    # ------------------------------------------------------------------
    # Sections
    # ------------------------------------------------------------------
    def _students_section(self, students):
        Employee = self.env['hr.employee'].sudo()
        teachers = Employee.search_count([('is_teacher', '=', True)])
        support = Employee.search_count([('school_staff_type', '=', 'support')])

        levels = students.level_id.sorted(lambda l: (l.sequence, l.id))
        by_level = {level.id: {'male': 0, 'female': 0, 'other': 0} for level in levels}
        for student in students:
            if student.level_id:
                by_level[student.level_id.id][student.gender or 'other'] += 1

        return {
            'students': {
                'enrolled': len(students),
                'boys': len(students.filtered(lambda s: s.gender == 'male')),
                'girls': len(students.filtered(lambda s: s.gender == 'female')),
                'boarders': len(students.filtered(lambda s: s.student_type == 'boarding')),
                'day': len(students.filtered(lambda s: s.student_type == 'day')),
                'teachers': teachers,
                'support_staff': support,
                'ratio': round(len(students) / teachers, 1) if teachers else 0,
            },
            'enrolment_by_level': {
                'labels': levels.mapped('name'),
                'level_ids': levels.ids,
                'male': [by_level[l.id]['male'] for l in levels],
                'female': [by_level[l.id]['female'] for l in levels],
                'other': [by_level[l.id]['other'] for l in levels],
            },
            'occupancy': self._occupancy(),
        }

    def _occupancy(self):
        rooms = self.env['school.hostel.room'].sudo().search([('hostel_id.active', '=', True)])
        routes = self.env['school.transport.route'].sudo().search([])
        return {
            'hostel': {'total': sum(rooms.mapped('beds')), 'used': sum(rooms.mapped('occupied'))},
            'transport': {'total': sum(routes.mapped('capacity')), 'used': sum(routes.mapped('seats_taken'))},
        }

    def _academics_section(self, students, term):
        Line = self.env['school.attendance.line'].sudo()
        today = fields.Date.context_today(self)

        # Today's attendance and classes still missing a confirmed register.
        today_counts = dict(Line._read_group(
            [('date', '=', today), ('attendance_id.state', '=', 'confirmed')],
            ['status'], ['__count']))
        total_today = sum(today_counts.values())
        present_today = today_counts.get('present', 0) + today_counts.get('late', 0)

        pending_registers = []
        school_day = today.weekday() < 5 and (
            not term or term.date_start <= today <= term.date_end)
        if school_day:
            confirmed = self.env['school.attendance'].sudo().search(
                [('date', '=', today), ('state', '=', 'confirmed')]).class_id
            for school_class in (students.class_id - confirmed).sorted('name'):
                pending_registers.append({'id': school_class.id, 'name': school_class.name})

        # Attendance trend: the last 14 days that have confirmed registers.
        trend = {'labels': [], 'dates': [], 'rates': []}
        since = today - timedelta(days=60)
        per_day = {}
        for day, status, count in Line._read_group(
                [('date', '>=', since), ('date', '<=', today), ('attendance_id.state', '=', 'confirmed')],
                ['date:day', 'status'], ['__count']):
            totals = per_day.setdefault(day, [0, 0])
            totals[1] += count
            if status in ('present', 'late'):
                totals[0] += count
        for day in sorted(per_day)[-14:]:
            present, total = per_day[day]
            trend['dates'].append(fields.Date.to_string(day))
            trend['labels'].append(day.strftime('%a %d %b'))
            trend['rates'].append(round(present / total * 100.0, 1) if total else 0)

        # Mean score per class for the term (marked results of exams past draft).
        scores = {'labels': [], 'class_ids': [], 'means': []}
        exams_marking = []
        if term:
            rows = self.env['school.exam.result'].sudo()._read_group(
                [('term_id', '=', term.id), ('mark_entered', '=', True), ('is_absent', '=', False),
                 ('exam_id.state', '!=', 'draft')],
                ['class_id'], ['percentage:avg'])
            for school_class, mean in sorted(rows, key=lambda r: r[1] or 0, reverse=True):
                scores['labels'].append(school_class.name)
                scores['class_ids'].append(school_class.id)
                scores['means'].append(round(mean or 0, 1))

            exams = self.env['school.exam'].sudo().search(
                [('term_id', '=', term.id), ('state', '=', 'ongoing')], order='date')
            for exam in exams:
                unmarked = len(exam.result_ids.filtered(lambda r: not r.mark_entered and not r.is_absent))
                exams_marking.append({
                    'id': exam.id, 'name': exam.name, 'class': exam.class_id.name,
                    'unmarked': unmarked, 'total': len(exam.result_ids),
                })

        return {
            'attendance': {
                'today_rate': round(present_today / total_today * 100.0, 1) if total_today else None,
                'today_marked': total_today,
                'absent_today': today_counts.get('absent', 0),
                'school_day': school_day,
            },
            'pending_registers': pending_registers,
            'attendance_trend': trend,
            'scores_by_class': scores,
            'exams_marking': exams_marking,
        }

    def _records_section(self):
        Admission = self.env['school.admission'].sudo()
        return {
            'admissions': {
                'pending': Admission.search_count([('state', 'in', ('submitted', 'review'))]),
                'accepted': Admission.search_count([('state', '=', 'accepted')]),
            },
        }

    def _fees_section(self, term):
        Move = self.env['account.move'].sudo()
        base = [('move_type', '=', 'out_invoice'), ('state', '=', 'posted'),
                ('student_id', '!=', False), ('company_id', 'in', self.env.companies.ids)]

        outstanding_total = Move._read_group(base, [], ['amount_residual_signed:sum'])[0][0] or 0.0

        fees = {'billed': 0.0, 'collected': 0.0, 'outstanding_term': 0.0,
                'outstanding_total': outstanding_total, 'rate': None}
        by_class = {'labels': [], 'class_ids': [], 'collected': [], 'outstanding': []}
        if term:
            per_class = {}
            for student, billed, residual in Move._read_group(
                    base + [('school_term_id', '=', term.id)],
                    ['student_id'], ['amount_total_signed:sum', 'amount_residual_signed:sum']):
                school_class = student.class_id
                totals = per_class.setdefault(school_class, [0.0, 0.0])
                totals[0] += billed or 0.0
                totals[1] += residual or 0.0
            for school_class, (billed, residual) in sorted(
                    per_class.items(), key=lambda item: item[0].name or ''):
                fees['billed'] += billed
                fees['outstanding_term'] += residual
                by_class['labels'].append(school_class.name or self.env._('No class'))
                by_class['class_ids'].append(school_class.id)
                by_class['collected'].append(round(billed - residual, 2))
                by_class['outstanding'].append(round(residual, 2))
            fees['collected'] = fees['billed'] - fees['outstanding_term']
            if fees['billed']:
                fees['rate'] = round(fees['collected'] / fees['billed'] * 100.0, 1)

        top = []
        for student, residual in Move._read_group(
                base + [('amount_residual_signed', '>', 0)],
                ['student_id'], ['amount_residual_signed:sum'],
                order='amount_residual_signed:sum desc', limit=6):
            top.append({'id': student.id, 'name': student.name,
                        'class': student.class_id.name or '', 'balance': residual})

        return {'fees': fees, 'fees_by_class': by_class, 'top_balances': top}

    def _library_section(self):
        Loan = self.env['school.library.loan'].sudo()
        return {
            'library': {
                'out': Loan.search_count([('state', 'in', ('issued', 'overdue'))]),
                'overdue': Loan.search_count([('state', '=', 'overdue')]),
            },
        }
