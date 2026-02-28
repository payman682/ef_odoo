from odoo import api, fields, models


class ClientEquipmentTechnicianHistoryWizard(models.TransientModel):
    _name = "client.equipment.technician.history.wizard"
    _description = "Technician History Wizard"

    date_from = fields.Date(string="From", required=True, default=lambda self: fields.Date.today().replace(day=1))
    date_to = fields.Date(string="To", required=True, default=fields.Date.context_today)

    technician_id = fields.Many2one(
        "res.users",
        string="Technician",
        domain=[("share", "=", False)],
        required=False,
    )

    partner_id = fields.Many2one("res.partner", string="Customer")
    equipment_id = fields.Many2one("client.equipment", string="Equipment")
    serial_search = fields.Char(string="Serial contains")

    only_done = fields.Boolean(string="Only Done Tasks")

    def action_show_tasks(self):
        self.ensure_one()

        domain = []

        # Date range based on task create_date (history of work orders created)
        if self.date_from:
            dt_from = fields.Datetime.to_datetime(self.date_from)
            domain.append(("create_date", ">=", dt_from))
        if self.date_to:
            # inclusive end of day
            dt_to = fields.Datetime.to_datetime(self.date_to)
            dt_to = dt_to.replace(hour=23, minute=59, second=59)
            domain.append(("create_date", "<=", dt_to))

        if self.technician_id:
            domain.append(("user_ids", "in", self.technician_id.id))

        if self.equipment_id:
            domain.append(("client_equipment_id", "=", self.equipment_id.id))

        if self.serial_search:
            domain.append(("client_equipment_id.serial_number", "ilike", self.serial_search))

        if self.partner_id:
            # Task customer OR equipment customer
            domain = ["|", ("partner_id", "=", self.partner_id.id), ("client_equipment_id.partner_id", "=", self.partner_id.id)] + domain

        if self.only_done:
            # Best effort: in standard project, folded stages usually represent 'done'
            domain.append(("stage_id.fold", "=", True))

        return {
            "type": "ir.actions.act_window",
            "name": "Technician History",
            "res_model": "project.task",
            "view_mode": "list,form,kanban",
            "domain": domain,
            "context": {
                "search_default_group_by_user": 0,
                "default_client_equipment_id": self.equipment_id.id if self.equipment_id else False,
            },
        }
