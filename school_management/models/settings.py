from odoo import api, fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    school_name = fields.Char(
        string='School Name',
        help='Shown as the app name, on the dashboard, report cards and the parent portal. '
             'Leave empty to keep the default "School".')


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    school_name = fields.Char(related='company_id.school_name', readonly=False)
    school_logo = fields.Binary(
        related='company_id.logo', readonly=False, string='School Logo',
        help='Printed in the letterhead of invoices, report cards and every other document. This is the '
             'company logo, so changing it here also changes it under Settings > Companies.')


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    @api.model
    def load_menus(self, debug):
        # Rename the School app tile after the current company's school. Applied on top of
        # the cached menu tree, so it follows the active company and survives upgrades.
        menus = super().load_menus(debug)
        school_name = self.env.company.sudo().school_name
        root = self.env.ref('school_management.menu_school_root', raise_if_not_found=False)
        if school_name and root and root.id in menus:
            menus = dict(menus)
            menus[root.id] = dict(menus[root.id], name=school_name)
        return menus
