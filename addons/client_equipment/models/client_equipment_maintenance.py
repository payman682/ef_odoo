from odoo import api, fields, models
from odoo.exceptions import ValidationError
from dateutil.relativedelta import relativedelta

import datetime

class ClientEquipmentMaintenance(models.Model):
    _name = "client.equipment.maintenance"
    _description = "Equipment Maintenance Schedule"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "next_service_date asc, id desc"

    equipment_id = fields.Many2one("client.equipment", required=True, ondelete="cascade", index=True)

    # UI/UX guardrail: when opening schedules from a specific equipment, lock the equipment selector.
    # (Odoo 17+ view modifiers do not use attrs/states; we rely on expressions + a context-dependent
    # computed boolean field.)
    lock_equipment_ctx = fields.Boolean(
        string="Lock Equipment",
        compute="_compute_lock_equipment_ctx",
        store=False,
        readonly=True,
    )

    @api.depends_context("from_equipment")
    def _compute_lock_equipment_ctx(self):
        lock = bool(self.env.context.get("from_equipment"))
        for rec in self:
            rec.lock_equipment_ctx = lock
    equipment_category_id = fields.Many2one(
        related="equipment_id.category_id",
        string="Equipment Category",
        store=True,
        readonly=True,
    )

    # Reporting helpers (stored, for pivot/graph)
    commercial_partner_id = fields.Many2one(
        related="equipment_id.partner_id.commercial_partner_id",
        string="Customer",
        store=True,
        readonly=True,
        index=True,
    )
    site_contact_id = fields.Many2one(
        related="equipment_id.site_contact_id",
        string="Site Contact",
        store=True,
        readonly=True,
        index=True,
    )
    equipment_site = fields.Char(
        related="equipment_id.site_name",
        string="Site",
        store=True,
        readonly=True,
    )
    equipment_serial = fields.Char(
        related="equipment_id.serial_number",
        string="Serial Number",
        store=True,
        readonly=True,
    )
    equipment_model = fields.Char(
        related="equipment_id.model",
        string="Model",
        store=True,
        readonly=True,
    )
    is_overdue = fields.Boolean(
        string="Overdue",
        compute="_compute_is_overdue",
        store=True,
        readonly=True,
        index=True,
    )

    pm_count = fields.Integer(
        string="Count",
        default=1,
        readonly=True,
        copy=False,
        aggregator="sum",
        store=True,
    )

    @api.depends("next_service_date")
    def _compute_is_overdue(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.is_overdue = bool(rec.next_service_date and rec.next_service_date < today)


    name = fields.Char(string="Schedule Name", required=True, tracking=True, default="Preventive Maintenance")

    interval_number = fields.Integer(string="Interval", default=3, required=True)
    interval_type = fields.Selection(
        [("days", "Days"), ("weeks", "Weeks"), ("months", "Months")],
        default="months",
        required=True,
    )

    last_service_date = fields.Date(tracking=True)
    next_service_date = fields.Date(compute="_compute_next_service_date", store=True, tracking=True)

    responsible_id = fields.Many2one("res.users", string="Responsible", default=lambda self: self.env.user)
    auto_create_task = fields.Boolean(string="Auto-create PM Task", default=True, tracking=True)
    active = fields.Boolean(default=True)
    notes = fields.Html()

    checklist_template_id = fields.Many2one(
        "client.equipment.pm.checklist.template",
        string="PM Checklist Template",
        default=lambda self: self.env.ref(
            "client_equipment.pm_checklist_template_forklift", raise_if_not_found=False
        ),
        help="Template used to prefill PM tasks checklist.",
    )

    
    @api.model_create_multi
    def create(self, vals_list):
        """Auto-name schedules when the user keeps the default name.

        Format: EquipmentName/YYYY/SEQ
        """
        # Enforce equipment when launched from a specific equipment (server-side safety).
        if self.env.context.get("from_equipment") and self.env.context.get("default_equipment_id"):
            forced_eq = self.env.context.get("default_equipment_id")
            for vals in vals_list:
                vals["equipment_id"] = forced_eq

        seq = self.env["ir.sequence"]
        today = fields.Date.context_today(self)
        year = today.year if today else datetime.date.today().year
        for vals in vals_list:
            name = vals.get("name")
            if not name or name == "Preventive Maintenance":
                eq_id = vals.get("equipment_id") or self.env.context.get("default_equipment_id")
                eq_name = False
                if eq_id:
                    eq = self.env["client.equipment"].browse(eq_id)
                    eq_name = eq.name or False
                nxt = seq.next_by_code("client.equipment.maintenance.schedule") or "00001"
                if eq_name:
                    vals["name"] = f"{eq_name}/{year}/{nxt}"
                else:
                    vals["name"] = f"PM/{year}/{nxt}"
        return super().create(vals_list)

    def write(self, vals):
        # Prevent changing equipment when opened from a specific equipment.
        if (
            self.env.context.get("from_equipment")
            and "equipment_id" in vals
            and any(rec.equipment_id.id != vals.get("equipment_id") for rec in self)
        ):
            raise ValidationError(
                "You cannot change the Equipment when creating a schedule from an Equipment record."
            )
        return super().write(vals)

    @api.constrains("equipment_id", "checklist_template_id")
    def _check_pm_template_matches_equipment_type(self):
        """Prevent assigning a template that doesn't match the equipment type."""
        for rec in self:
            if not rec.equipment_id or not rec.checklist_template_id:
                continue
            eq_cat = rec.equipment_id.category_id
            tpl_cat = rec.checklist_template_id.category_id
            if eq_cat and tpl_cat and eq_cat != tpl_cat:
                raise ValidationError(
                    "PM Checklist Template equipment type must match the Equipment Category."
                )

    @api.depends("last_service_date", "interval_number", "interval_type")
    def _compute_next_service_date(self):
        for rec in self:
            base = rec.last_service_date or fields.Date.context_today(rec)
            if rec.interval_type == "days":
                rec.next_service_date = base + relativedelta(days=rec.interval_number)
            elif rec.interval_type == "weeks":
                rec.next_service_date = base + relativedelta(weeks=rec.interval_number)
            else:
                rec.next_service_date = base + relativedelta(months=rec.interval_number)

    def _cron_generate_due_tasks(self):
        today = fields.Date.context_today(self)
        schedules = self.search([
            ("active", "=", True),
            ("auto_create_task", "=", True),
            ("next_service_date", "!=", False),
            ("next_service_date", "<=", today),
        ])
        for s in schedules:
            eq = s.equipment_id
            if not eq or not eq.active:
                continue
            project = eq._ensure_maintenance_project()
            existing = self.env["project.task"].search([
                ("pm_schedule_id", "=", s.id),
                ("pm_completed", "=", False),
                ("stage_id.fold", "=", False),
            ], limit=1)
            if not existing:
                pm_number = eq._reserve_next_pm_number()
                vals = {
                    "name": f"PM #{pm_number} - {eq.name} ({eq.serial_number})",
                    "pm_sequence": pm_number,
                    "project_id": project.id,
                    "date_deadline": s.next_service_date,
                    "user_ids": [(6, 0, [s.responsible_id.id])] if s.responsible_id else False,
                    "client_equipment_id": eq.id,
                    "pm_schedule_id": s.id,
                    "pm_checklist_line_ids": self.env["project.task"]._pm_prepare_checklist_commands(s.checklist_template_id),
                    "description": (s.notes or "") + f"\n\nPreventive maintenance every {s.interval_number} {s.interval_type}.",
                }
                if "partner_id" in self.env["project.task"]._fields:
                    vals["partner_id"] = (eq.site_contact_id or eq.partner_id).id
                self.env["project.task"].create(vals)