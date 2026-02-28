
from odoo import api, fields, models
from odoo.exceptions import ValidationError, UserError
from dateutil.relativedelta import relativedelta

class ClientEquipment(models.Model):
    _name = "client.equipment"
    _description = "Client Equipment"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "partner_id, name"

    name = fields.Char(string="Equipment Name", required=True, tracking=True)
    partner_id = fields.Many2one("res.partner", string="Customer", required=True, index=True, tracking=True)
    category_id = fields.Many2one("client.equipment.category", string="Category", ondelete="restrict", tracking=True)

    manufacturer_id = fields.Many2one(
        "client.equipment.manufacturer",
        string="Manufacturer (Dropdown)",
        ondelete="restrict",
        tracking=True,
    )
    manufacturer_logo = fields.Image(related="manufacturer_id.logo", readonly=True, string="Manufacturer Logo")
    model = fields.Char(string="Model", tracking=True)
    serial_number = fields.Char(string="Serial Number", required=True, index=True, tracking=True)
    asset_tag = fields.Char(string="Asset Tag / Unit Code", tracking=True)

    barcode = fields.Char(string="Barcode", index=True, tracking=True,
                          help="Scan to find this equipment (defaults to Serial Number).")

    site_contact_id = fields.Many2one(
        "res.partner",
        string="Site (Contact)",
        help="Choose the customer site/location from the customer's child contacts (Contacts tab).",
        index=True,
    )

    site_name = fields.Char(string="Site Name", related="site_contact_id.name", store=True, readonly=True)
    site_street = fields.Char(string="Street", related="site_contact_id.street", store=True, readonly=True)
    site_city = fields.Char(string="City", related="site_contact_id.city", store=True, readonly=True)
    site_state = fields.Char(string="State/Province", related="site_contact_id.state_id.name", store=True, readonly=True)
    site_zip = fields.Char(string="Postal Code", related="site_contact_id.zip", store=True, readonly=True)
    site_country_id = fields.Many2one("res.country", string="Country", related="site_contact_id.country_id", store=True, readonly=True)

    warranty_provider = fields.Char(string="Warranty Provider", tracking=True)
    warranty_start_date = fields.Date(string="Warranty Start", tracking=True)
    warranty_end_date = fields.Date(string="Warranty End", tracking=True)
    warranty_notes = fields.Html(string="Warranty Notes")
    warranty_active = fields.Boolean(string="Warranty Active", compute="_compute_warranty_active", store=True, index=True)

    maintenance_ids = fields.One2many("client.equipment.maintenance", "equipment_id", string="Maintenance Schedules")
    maintenance_project_id = fields.Many2one(
        "project.project",
        string="Maintenance Project",
        help="Project where preventive maintenance tasks will be created (optional).",
    )


    pm_sequence_next = fields.Integer(
        string="Next PM Number",
        default=1,
        help="Next preventive maintenance number for this equipment. Used to generate unique PM task titles (PM #N).",
    )

    # Hour meter (odometer-like) tracking
    hour_meter_current = fields.Integer(
        string="Current Hours",
        tracking=True,
        help="Latest known hour meter reading for this equipment.",
    )
    hour_meter_updated_on = fields.Datetime(
        string="Hours Updated On",
        tracking=True,
        readonly=True,
        help="Last time the equipment hour meter was updated from a completed service task.",
    )

    hourmeter_log_ids = fields.One2many(
        "client.equipment.hourmeter.log",
        "equipment_id",
        string="Hour Meter History",
        readonly=True,
    )

    task_ids = fields.One2many("project.task", "client_equipment_id", string="Service Tasks")

    # PM follow-up flag (set when PM checklist contains Not OK items)
    needs_attention = fields.Boolean(
        string="Needs Attention",
        tracking=True,
        help="Set automatically when a PM is completed with one or more checklist items marked Not OK.",
    )
    attention_reason = fields.Char(string="Attention Reason", tracking=True)
    attention_date = fields.Date(string="Attention Date", tracking=True)

    notes = fields.Html(string="Notes")
    active = fields.Boolean(default=True)

    # Attachments
    attachment_ids = fields.Many2many(
        "ir.attachment",
        "client_equipment_ir_attachment_rel",
        "equipment_id",
        "attachment_id",
        string="Legacy Attachments",
        help="Legacy linkage (deprecated). New installations should use Equipment Attachments below.",
    )

    # Recommended attachment linkage: bind ir.attachment to equipment via client_equipment_id
    # This keeps res_model/res_id consistent and avoids floating M2M links.
    equipment_attachment_ids = fields.One2many(
        "ir.attachment",
        "client_equipment_id",
        string="Equipment Attachments",
        help="Files attached to this equipment.",
    )
    equipment_attachment_count = fields.Integer(
        string="Equipment Attachments Count",
        compute="_compute_equipment_attachment_count",
    )

    def _compute_equipment_attachment_count(self):
        Attachment = self.env["ir.attachment"]
        for rec in self:
            # Count only attachments the current user can access (no sudo)
            rec.equipment_attachment_count = Attachment.search_count([
                ("client_equipment_id", "=", rec.id),
            ])

    def action_open_equipment_attachments(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Equipment Attachments",
            "res_model": "ir.attachment",
            "view_mode": "list,form",
            "domain": [("client_equipment_id", "=", self.id)],
            "context": {
                "default_client_equipment_id": self.id,
                "default_res_model": "client.equipment",
                "default_res_id": self.id,
            },
            "target": "current",
        }

    # Task attachments (history): files attached to service tasks linked to this equipment
    task_attachment_count = fields.Integer(
        string="Task Attachments",
        compute="_compute_task_attachment_count",
    )

    def _compute_task_attachment_count(self):
        Attachment = self.env["ir.attachment"]
        for rec in self:
            task_ids = rec.task_ids.ids
            if not task_ids:
                rec.task_attachment_count = 0
                continue
            # Count only attachments the current user can access (no sudo)
            rec.task_attachment_count = Attachment.search_count([
                ("res_model", "=", "project.task"),
                ("res_id", "in", task_ids),
            ])

    def action_open_task_attachments(self):
        self.ensure_one()
        task_ids = self.task_ids.ids
        return {
            "type": "ir.actions.act_window",
            "name": "Task Attachments",
            "res_model": "ir.attachment",
            "view_mode": "list,form",
            "domain": [
                ("res_model", "=", "project.task"),
                ("res_id", "in", task_ids),
            ],
            "context": {
                "default_res_model": "project.task",
            },
            "target": "current",
        }

    # Odoo 19+: SQL constraints are defined via models.Constraint attributes
    _barcode_unique = models.Constraint(
        "UNIQUE(barcode)",
        "Barcode must be unique.",
    )

    @api.depends("warranty_start_date", "warranty_end_date")


    def _compute_warranty_active(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.warranty_start_date and today < rec.warranty_start_date:
                rec.warranty_active = False
            elif rec.warranty_end_date and today > rec.warranty_end_date:
                rec.warranty_active = False
            elif rec.warranty_start_date or rec.warranty_end_date:
                rec.warranty_active = True
            else:
                rec.warranty_active = False

    @api.constrains("serial_number")
    def _check_serial_number(self):
        for rec in self:
            if rec.serial_number and len(rec.serial_number.strip()) < 3:
                raise ValidationError("Serial Number looks too short.")

    
    @api.constrains("partner_id", "site_contact_id", "serial_number")
    def _check_serial_unique_per_customer_site(self):
        """C2 rule:
        - If Site is set: (Customer, Site, Serial) must be unique
        - If Site is empty: (Customer, Serial) must be unique
        Only enforces when serial_number and partner_id are set.
        """
        for rec in self:
            if not rec.partner_id or not rec.serial_number:
                continue
            domain = [
                ("id", "!=", rec.id),
                ("partner_id", "=", rec.partner_id.id),
                ("serial_number", "=", rec.serial_number),
            ]
            if rec.site_contact_id:
                domain.append(("site_contact_id", "=", rec.site_contact_id.id))
            else:
                domain.append(("site_contact_id", "=", False))
            if self.search_count(domain):
                if rec.site_contact_id:
                    raise ValidationError(
                        "Serial Number must be unique per Customer and Site."
                    )
                raise ValidationError(
                    "Serial Number must be unique per Customer when Site is empty."
                )


    @api.onchange("partner_id")
    def _onchange_partner_id_clear_site(self):
        for rec in self:
            if (
                rec.site_contact_id
                and rec.partner_id
                and rec.site_contact_id not in rec.partner_id.child_ids
            ):
                rec.site_contact_id = False

    @api.onchange("site_contact_id")
    def _onchange_site_contact_id_fill_address(self):
        for rec in self:
            if rec.site_contact_id and rec.partner_id and rec.site_contact_id not in rec.partner_id.child_ids:
                rec.site_contact_id = False
                return
            # site fields are related and auto-filled

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if not rec.barcode and rec.serial_number:
                rec.barcode = rec.serial_number
        return records

    def write(self, vals):
        res = super().write(vals)
        for rec in self:
            if not rec.barcode and rec.serial_number:
                rec.barcode = rec.serial_number
        return res

    def action_open_maintenance(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Maintenance Schedules",
            "res_model": "client.equipment.maintenance",
            "view_mode": "list,form",
            "domain": [("equipment_id", "=", self.id)],
            "context": {"default_equipment_id": self.id, "from_equipment": True},
        }

    def _reserve_next_pm_number(self):
        """Atomically reserve the next PM number for this equipment.

        Concurrency-safe: uses a row lock to prevent duplicates when cron and users create PMs at the same time.
        """
        self.ensure_one()
        cr = self.env.cr
        cr.execute("SELECT pm_sequence_next FROM client_equipment WHERE id=%s FOR UPDATE", (self.id,))
        row = cr.fetchone()
        current = (row[0] if row and row[0] is not None else 1) or 1
        cr.execute("UPDATE client_equipment SET pm_sequence_next=%s WHERE id=%s", (current + 1, self.id))
        self.invalidate_recordset(["pm_sequence_next"])
        return current


    def _ensure_maintenance_project(self):
        self.ensure_one()
        project = self.maintenance_project_id
        if project:
            return project
        project = self.env["project.project"].search([("name", "=", "Maintenance")], limit=1)
        if not project:
            project = self.env["project.project"].create({"name": "Maintenance", "privacy_visibility": "followers"})
        self.maintenance_project_id = project.id
        return project

    def action_create_pm_task(self):
        """Open PM wizard (inspection-like UX).

        We intentionally do NOT create the task immediately, so dispatch can review the defaults.
        """
        self.ensure_one()
        schedules = self.maintenance_ids.filtered(lambda s: s.active and s.next_service_date)
        schedule = schedules.sorted(lambda s: s.next_service_date)[:1]
        if not schedule:
            raise UserError("No active maintenance schedule found. Create a schedule first.")
        schedule = schedule[0]

        return {
            "type": "ir.actions.act_window",
            "name": "New PM",
            "res_model": "client.equipment.pm.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_equipment_id": self.id,
                "default_schedule_id": schedule.id,
                "from_equipment": True,
            },
        }

    def _get_fsm_project(self):
        """Return a Field Service-enabled project for the current company."""
        Project = self.env["project.project"]
        domain = [("company_id", "in", [False, self.env.company.id])]
        # Common FSM flags across versions
        for f in ("is_fsm", "fsm_project", "allow_fsm"):
            if f in Project._fields:
                domain.append((f, "=", True))
                break
        project = Project.search(domain, limit=1)
        if not project:
            raise UserError(
                "No Field Service project found. Enable 'Field Service' on a project first "
                "(Field Service → Configuration → Projects)."
            )
        return project

    def action_create_fsm_task(self):
        self.ensure_one()
        project = self._get_fsm_project()

        task_vals = {
            "name": f"Service: {self.name} ({self.serial_number})",
            "project_id": project.id,
            "partner_id": self.partner_id.id,
            "client_equipment_id": self.id,
        }

        Task = self.env["project.task"]
        if "is_fsm" in Task._fields:
            task_vals["is_fsm"] = True

        # Allow technicians to add products/services on the task when the feature is installed.
        # This is UI/behavior enablement only; it does not create invoices automatically.
        if "allow_billable" in Task._fields:
            task_vals["allow_billable"] = True

        task = Task.create(task_vals)

        # Prefer opening through the Field Service action (so worksheet/products tabs appear)
        action = None
        for xml_id in (
            "industry_fsm.project_task_action_fsm",
            "industry_fsm.project_task_action_view",
            "industry_fsm.action_project_task_fsm",
        ):
            try:
                action = self.env.ref(xml_id).read()[0]
                break
            except Exception:
                continue

        if not action:
            action = {
                "type": "ir.actions.act_window",
                "name": "Task",
                "res_model": "project.task",
                "view_mode": "form",
            }

        action.update({"res_id": task.id, "views": [(False, "form")]})
        return action