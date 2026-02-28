from odoo import api, fields, models
from odoo.exceptions import UserError


class ClientEquipmentNewPMWizard(models.TransientModel):
    _name = "client.equipment.pm.wizard"
    _description = "New PM (Create Task)"

    lock_equipment = fields.Boolean(
        string="Lock Equipment",
        default=lambda self: bool(self.env.context.get("from_equipment")),
        readonly=True,
    )

    equipment_id = fields.Many2one(
        "client.equipment",
        string="Client Equipment",
        required=True,
        ondelete="cascade",
    )

    schedule_id = fields.Many2one(
        "client.equipment.maintenance",
        string="Maintenance Schedule",
        required=True,
        domain="[('equipment_id','=',equipment_id), ('active','=',True)]",
    )

    service_project_id = fields.Many2one(
        "project.project",
        string="Service Project",
        required=True,
    )

    technician_id = fields.Many2one("res.users", string="Technician")

    equipment_category_id = fields.Many2one(
        "client.equipment.category",
        string="Equipment Type",
        compute="_compute_equipment_category_id",
        store=False,
        readonly=True,
    )

    template_id = fields.Many2one(
        related="schedule_id.checklist_template_id",
        string="PM Checklist Template",
        readonly=True,
    )

    due_date = fields.Date(string="Due Date")

    @api.depends("equipment_id")
    def _compute_equipment_category_id(self):
        for wizard in self:
            wizard.equipment_category_id = wizard.equipment_id.category_id

    @api.depends("schedule_id")
    def _compute_template_id(self):
        for wizard in self:
            wizard.template_id = wizard.schedule_id.checklist_template_id if wizard.schedule_id else False

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        equipment_id = res.get("equipment_id") or self.env.context.get("default_equipment_id")
        schedule_id = res.get("schedule_id") or self.env.context.get("default_schedule_id")
        # Context-sensitive behavior
        if self.env.context.get("from_equipment"):
            if equipment_id and "equipment_id" in fields_list and not res.get("equipment_id"):
                res["equipment_id"] = equipment_id
            if "lock_equipment" in fields_list:
                res["lock_equipment"] = True
        if equipment_id:
            equipment = self.env["client.equipment"].browse(equipment_id)
            # Default project: equipment maintenance project or auto-created "Maintenance"
            if "service_project_id" in fields_list and not res.get("service_project_id"):
                if equipment.maintenance_project_id:
                    res["service_project_id"] = equipment.maintenance_project_id.id
                else:
                    res["service_project_id"] = equipment._ensure_maintenance_project().id

            # Default schedule: soonest upcoming
            if "schedule_id" in fields_list and not schedule_id:
                schedules = equipment.maintenance_ids.filtered(lambda s: s.active and s.next_service_date)
                schedule = schedules.sorted(lambda s: s.next_service_date)[:1]
                if schedule:
                    res["schedule_id"] = schedule[0].id

        if schedule_id and "due_date" in fields_list and not res.get("due_date"):
            sched = self.env["client.equipment.maintenance"].browse(schedule_id)
            res["due_date"] = sched.next_service_date

        # Default tech: schedule responsible, else current user
        if "technician_id" in fields_list and not res.get("technician_id"):
            if schedule_id:
                sched = self.env["client.equipment.maintenance"].browse(schedule_id)
                if sched.responsible_id:
                    res["technician_id"] = sched.responsible_id.id
                else:
                    res["technician_id"] = self.env.user.id
            else:
                res["technician_id"] = self.env.user.id

        return res

    @api.onchange("equipment_id")
    def _onchange_equipment_id(self):
        for wizard in self:
            if wizard.lock_equipment and self.env.context.get("default_equipment_id"):
                wizard.equipment_id = self.env["client.equipment"].browse(self.env.context.get("default_equipment_id"))
            if wizard.equipment_id:
                # Keep schedule consistent with selected equipment
                if wizard.schedule_id and wizard.schedule_id.equipment_id != wizard.equipment_id:
                    wizard.schedule_id = False
                if wizard.schedule_id:
                    wizard.due_date = wizard.schedule_id.next_service_date

    @api.onchange("schedule_id")
    def _onchange_schedule_id(self):
        for wizard in self:
            if wizard.schedule_id:
                wizard.due_date = wizard.schedule_id.next_service_date

    def action_create_task_and_open(self):
        self.ensure_one()

        # Server-side enforcement: if wizard opened from an Equipment, do not allow switching.
        if self.lock_equipment and self.env.context.get("default_equipment_id"):
            if self.equipment_id.id != self.env.context.get("default_equipment_id"):
                raise UserError("This PM wizard is locked to the selected equipment.")

        if not self.schedule_id:
            raise UserError("Please select a Maintenance Schedule.")

        # Locked rule: template comes from schedule
        template = self.schedule_id.checklist_template_id
        if not template:
            raise UserError("This Maintenance Schedule has no PM Checklist Template configured.")

        equipment = self.equipment_id

        # Enforce sync: equipment category must match template category
        if equipment.category_id and template.category_id and equipment.category_id != template.category_id:
            raise UserError("Schedule template does not match the equipment type.")

        Task = self.env["project.task"]

        # Duplicate prevention (hard block): reuse existing OPEN PM task for the same schedule
        # NOTE: 'open' is defined as stage not closed (fold=False). Configure your Done stages as folded/closed.
        existing = Task.search(
            [
                ("pm_schedule_id", "=", self.schedule_id.id),
                ("client_equipment_id", "=", equipment.id),
                ("stage_id.fold", "=", False),
            ],
            limit=1,
        )
        if existing:
            return {
                "type": "ir.actions.act_window",
                "name": "PM Task",
                "res_model": "project.task",
                "view_mode": "form",
                "res_id": existing.id,
                "target": "current",
            }

        project = self.service_project_id or equipment._ensure_maintenance_project()
        partner = equipment.site_contact_id or equipment.partner_id

        pm_number = equipment._reserve_next_pm_number()

        vals = {
            "name": f"PM #{pm_number} - {equipment.name} ({equipment.serial_number})",
            "pm_sequence": pm_number,
            "project_id": project.id,
            "date_deadline": self.due_date or self.schedule_id.next_service_date,
            "client_equipment_id": equipment.id,
            "pm_schedule_id": self.schedule_id.id,
            "pm_checklist_line_ids": Task._pm_prepare_checklist_commands(template),
            "description": (self.schedule_id.notes or "") + f"\n\nPreventive maintenance every {self.schedule_id.interval_number} {self.schedule_id.interval_type}.",
        }

        if "partner_id" in Task._fields:
            vals["partner_id"] = partner.id

        if self.technician_id:
            if "user_ids" in Task._fields:
                vals["user_ids"] = [(6, 0, [self.technician_id.id])]
            elif "user_id" in Task._fields:
                vals["user_id"] = self.technician_id.id

        task = Task.create(vals)

        return {
            "type": "ir.actions.act_window",
            "name": "PM Task",
            "res_model": "project.task",
            "view_mode": "form",
            "res_id": task.id,
            "target": "current",
        }

