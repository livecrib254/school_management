{
    'name': 'School Management',
    'version': '19.0.1.12.0',
    'category': 'Education',
    'summary': 'Admissions, students, academics, exams, fees, staff, library, transport and hostel for Kenyan schools (CBC and 8-4-4)',
    'description': """
School Management for Kenyan schools
====================================
* Admissions workflow and student records (NEMIS UPI, guardians, class history)
* Classes/streams, subjects, timetable with clash detection, daily attendance
* Exams, mark entry, CBC 8-level and KCSE grade scales, report cards with class positions
* Fee structures, term invoice generation on top of Odoo Accounting, bursary discounts
* Teachers, library loans with fines, school transport, hostel allocation
* Parent portal page with published report cards and fee balance
* Announcements and guardian messages by portal, email and SMS; SMS fee reminders
""",
    'author': 'Livecrib Solutions Ltd',
    'maintainer': 'Livecrib Solutions Ltd',
    'website': 'https://www.livecrib.pro',
    'support': 'support@livecrib.pro',
    'license': 'LGPL-3',
    'images': [
        'static/description/banner.png',
    ],
    'depends': ['base', 'mail', 'hr', 'account', 'portal', 'sms'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/sequence_data.xml',
        'data/grade_scale_data.xml',
        'data/grade_level_data.xml',
        'data/fee_product_data.xml',
        'data/staff_role_data.xml',
        'data/ir_cron_data.xml',
        'data/sms_template_data.xml',
        'report/report_card.xml',
        'report/invoice_report.xml',
        'report/timetable_report.xml',
        'report/fee_statement.xml',
        'views/academic_views.xml',
        'views/student_views.xml',
        'views/admission_views.xml',
        'views/attendance_views.xml',
        'views/exam_views.xml',
        'views/fee_views.xml',
        'views/account_move_views.xml',
        'views/staff_views.xml',
        'views/library_views.xml',
        'views/transport_views.xml',
        'views/hostel_views.xml',
        'wizards/wizard_views.xml',
        'views/portal_templates.xml',
        'views/communication_views.xml',
        'views/sms_views.xml',
        'views/dashboard_views.xml',
        'views/settings_views.xml',
        'views/menus.xml',
    ],
    'demo': [
        'demo/demo.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'school_management/static/src/dashboard/*',
            'school_management/static/src/timetable/*',
        ],
    },
    'application': True,
    'installable': True,
}
