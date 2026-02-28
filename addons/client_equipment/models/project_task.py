from odoo import api, fields, models
from odoo.exceptions import UserError

import datetime


class ProjectTask(models.Model):
    _inherit = "project.task"

    # Equipment link
    client_equipment_id = fields.Many2one(
        "client.equipment",
        string="Client Equipment",
        index=True,
        tracking=True,
    )

    # Helper fields shown on the task (read-only, derived from equipment)
    equipment_serial = fields.Char(
        related="client_equipment_id.serial_number",
        string="Serial Number",
        store=True,
        readonly=True,
    )

    equipment_site = fields.Char(
        related="client_equipment_id.site_name",
        string="Site",
        store=True,
        readonly=True,
    )

    equipment_model = fields.Char(
        related="client_equipment_id.model",
        string="Model",
        store=True,
        readonly=True,
    )

    # Pivot/report helper: always 1, aggregated by sum = record count
    service_history_count = fields.Integer(
        string="Count",
        default=1,
        readonly=True,
        copy=False,
        aggregator="sum",
        store=True,
    )

    # Reporting helpers (stored for pivot/graph)
    technician_id = fields.Many2one(
        "res.users",
        string="Primary Technician",
        compute="_compute_technician_id",
        store=True,
        readonly=True,
        index=True,
        help="Reporting helper: first assigned technician (from user_ids).",
    )

    service_kind = fields.Selection(
        selection=[("pm", "PM"), ("service", "Service/Repair")],
        string="Service Kind",
        compute="_compute_service_kind",
        store=True,
        readonly=True,
        index=True,
        help="Reporting helper: PM if linked to a PM schedule, else Service/Repair.",
    )

    service_duration_hours = fields.Float(
        string="Completion Time (Hours)",
        compute="_compute_service_kpis",
        store=True,
        readonly=True,
        aggregator="avg",
        help="Reporting KPI: time from creation to completion (approx).",
    )

    delay_days = fields.Float(
        string="Delay vs Deadline (Days)",
        compute="_compute_service_kpis",
        store=True,
        readonly=True,
        aggregator="avg",
        help="Reporting KPI: completion date minus deadline in days (positive means late).",
    )

    is_overdue = fields.Boolean(
        string="Overdue",
        compute="_compute_is_overdue",
        store=True,
        readonly=True,
        index=True,
        help="True if deadline is in the past and the task is not in a folded stage.",
    )

    @api.depends("user_ids")
    def _compute_technician_id(self):
        for task in self:
            users = getattr(task, "user_ids", self.env["res.users"])
            task.technician_id = users[:1].id if users else False

    @api.depends("pm_schedule_id", "pm_sequence")
    def _compute_service_kind(self):
        for task in self:
            task.service_kind = "pm" if (task.pm_schedule_id or task.pm_sequence) else "service"

    @api.depends("create_date", "write_date", "date_deadline", "stage_id.fold")
    def _compute_service_kpis(self):
        for task in self:
            done_dt = task.write_date if task.stage_id and task.stage_id.fold else False
            if task.create_date and done_dt:
                delta = done_dt - task.create_date
                task.service_duration_hours = delta.total_seconds() / 3600.0
            else:
                task.service_duration_hours = 0.0

            if task.date_deadline and done_dt:
                if isinstance(task.date_deadline, datetime.datetime):
                    deadline_dt = task.date_deadline
                else:
                    deadline_dt = datetime.datetime.combine(task.date_deadline, datetime.time.min)
                task.delay_days = (done_dt - deadline_dt).total_seconds() / 86400.0
            else:
                task.delay_days = 0.0

    @api.depends("date_deadline", "stage_id.fold")
    def _compute_is_overdue(self):
        today = fields.Date.context_today(self)
        for task in self:
            if task.stage_id and task.stage_id.fold:
                task.is_overdue = False
            elif task.date_deadline:
                dl = task.date_deadline.date() if isinstance(task.date_deadline, datetime.datetime) else task.date_deadline
                task.is_overdue = bool(dl and dl < today)
            else:
                task.is_overdue = False

    service_type = fields.Selection(
        selection=[
            ("on_site", "On-site (Client)"),
            ("workshop", "Workshop (In shop)"),
        ],
        string="Service Type",
        default="on_site",
        tracking=True,
        required=True,
    )

    # PM linkage (completion-based scheduling)
    pm_schedule_id = fields.Many2one(
        "client.equipment.maintenance",
        string="PM Schedule",
        readonly=True,
        index=True,
    )

    pm_sequence = fields.Integer(
        string="PM Number",
        readonly=True,
        index=True,
        help="Sequential PM number for this equipment (PM #N).",
    )
    pm_completed = fields.Boolean(string="PM Completed", readonly=True, default=False, index=True)
    pm_completed_date = fields.Date(string="PM Completed On", readonly=True)

    # Hour meter captured on service
    hour_meter_reading = fields.Integer(
        string="Hour Meter (at Service)",
        help="Hour meter reading captured for this task. When the task is marked Done, the equipment Current Hours will be updated.",
    )
    hour_meter_previous = fields.Integer(
        string="Previous Hours",
        readonly=True,
        help="Equipment hours at the time this task was created (for reference).",
    )
    hour_meter_delta = fields.Integer(
        string="Hours Since Previous",
        compute="_compute_hour_meter_delta",
        store=False,
    )
    hour_meter_logged = fields.Boolean(
        string="Hour Meter Logged",
        default=False,
        readonly=True,
        help="Technical flag to prevent logging/updating equipment hours multiple times for the same task.",
    )

    # Signatures (for PM / Job Confirmation reports)
    tech_signature = fields.Binary(string="Technician Signature")
    tech_signed_name = fields.Char(string="Technician Name")
    tech_signed_on = fields.Datetime(string="Technician Signed On")

    customer_signature = fields.Binary(string="Customer Signature")
    customer_signed_name = fields.Char(string="Customer Name")
    customer_signed_on = fields.Datetime(string="Customer Signed On")

    # ---------------------------------------------------------------------
    # Partner normalization for Equipment-linked tasks
    # ---------------------------------------------------------------------
    def _get_equipment_commercial_partner_id(self, equipment):
        """Return the commercial partner id for an equipment, or False."""
        partner = equipment.partner_id
        return partner.commercial_partner_id.id if partner else False

    @api.onchange("client_equipment_id")
    def _onchange_client_equipment_id_set_partner(self):
        """Ensure partner_id is the *Customer* (commercial entity).

        Site is represented separately (equipment_site) and should not drive partner_id.
        This keeps reporting/grouping stable: Customer -> Site.
        """
        for task in self:
            if not task.client_equipment_id:
                continue
            commercial_partner_id = task._get_equipment_commercial_partner_id(task.client_equipment_id)
            if commercial_partner_id:
                task.partner_id = commercial_partner_id




    service_status = fields.Selection(
        selection=[
            ("planned", "Planned"),
            ("in_progress", "In Progress"),
            ("done", "Done"),
        ],
        string="Status",
        compute="_compute_service_status",
        store=False,
    )

    def _stage_is_closed(self, stage):
        """Authoritative closure detection.

        Best practice: stages that represent completion must be configured as closed.
        We treat a stage as closed if:
        - stage.is_closed is True (if the field exists), OR
        - stage.fold is True (classic Odoo 'Done' columns)
        """
        if not stage:
            return False
        if hasattr(stage, "is_closed") and stage.is_closed:
            return True
        if getattr(stage, "fold", False):
            return True
        return False

    def _compute_service_status(self):
        """Status used only for Equipment > Service History.

        Source of truth:
        - If Industry FSM provides a task 'state', we mirror it so the badge is consistent
          with what technicians see on the FSM task.
        - Otherwise, we fallback to Project stage closure (is_closed / fold).

        Mapping:
        - done        => FSM state is done, OR stage is closed (is_closed/fold)
        - in_progress => FSM state indicates progress, OR stage is not closed and not early
        - planned     => everything else / early stages
        """
        for task in self:
            # 1) Prefer FSM completion flags/state when available (keeps UI consistent with Field Service)
            if "fsm_done" in task._fields and task.fsm_done:
                task.service_status = "done"
                continue

            if "state" in task._fields:
                st = (task.state or "").strip().lower()

                # Some FSM selections use values like "01_in_progress" / "1_done"
                if st == "done" or st.endswith("done") or "done" in st or st in ("closed", "close"):
                    task.service_status = "done"
                    continue

                if st in ("in_progress", "progress") or "progress" in st or "in_progress" in st:
                    task.service_status = "in_progress"
                    continue

                if st in ("planned", "new", "draft") or "plan" in st or st in ("todo", "to_do"):
                    task.service_status = "planned"
                    continue
                # If state exists but has unexpected value, fallback to stage logic.

            # 2) Fallback: stage-based closure
            stage = task.stage_id
            if task._stage_is_closed(stage):
                task.service_status = "done"
                continue

            stage_name = (stage.name or "").strip().lower() if stage else ""
            if stage_name in ("done", "closed") or stage_name.endswith("done") or "done" in stage_name or "close" in stage_name:
                task.service_status = "done"
                continue
            if not stage or stage_name in ("new", "planned") or getattr(stage, "sequence", 0) <= 1:
                task.service_status = "planned"
            else:
                task.service_status = "in_progress"

    def _compute_hour_meter_delta(self):
        for task in self:
            if task.hour_meter_reading is not None and task.hour_meter_previous is not None:
                # Business rule: hour meter deltas should never be negative in UI.
                # If reading is lower than previous, we show 0 and we handle the anomaly
                # during completion (warn + ignore equipment update).
                task.hour_meter_delta = max(0, task.hour_meter_reading - task.hour_meter_previous)
            else:
                task.hour_meter_delta = 0

    def _is_done_event(self):
        """Return True if the task is considered Done/Closed.

        For sync consistency with Industry FSM:
        - Prefer FSM fields (fsm_done/state) when available.
        - Fallback to stage closure.
        """
        self.ensure_one()

        if "fsm_done" in self._fields and self.fsm_done:
            return True

        if "state" in self._fields:
            st = (self.state or "").strip().lower()
            if st == "done" or st.endswith("done") or "done" in st or st in ("closed", "close"):
                return True

        return self._stage_is_closed(self.stage_id)

    def _is_done_state(self):
        """Return True if the task is considered done/closed.

        Odoo Field Service (Industry FSM) can mark a task as done using `fsm_done`
        even when the Project stage is not configured as closed/folded.
        We therefore use the unified completion rule in `_is_done_event()`.
        """
        self.ensure_one()
        return self._is_done_event()

    def _validate_pm_before_close(self, new_stage=None):
        """Enforce PM completion requirements before a PM task can be closed.

        Applies ONLY to PM tasks (pm_schedule_id set).
        - Checklist must exist (at least one line)
        - Technician + Customer signatures must exist

        NOTE: We intentionally do NOT enforce this for non-PM tasks to avoid breaking FSM repairs.
        """
        for task in self:
            if not task.pm_schedule_id:
                continue

            stage = new_stage or task.stage_id
            if not task._stage_is_closed(stage):
                continue

            if not task.pm_checklist_line_ids:
                raise UserError("PM checklist is required before completing the PM task.")

            if not task.tech_signature:
                raise UserError("Technician signature is required before completing the PM task.")
            # Customer signature: manager override only
            if not task.customer_signature and not self.env.user.has_group(
                "client_equipment.group_pm_manager_override"
            ):
                raise UserError(
                    "Customer signature is required to complete the PM task. "
                    "A PM Manager Override user can close it without customer signature."
                )

    
    def _get_task_done_date(self):
        """Best-effort completion date for KPI and PM schedule updates.

        Uses the record's write_date (stage change) in the user's timezone.
        Falls back to today if write_date is not available.
        """
        self.ensure_one()
        done_dt = self.write_date or fields.Datetime.now()
        done_dt_local = fields.Datetime.context_timestamp(self, done_dt)
        return done_dt_local.date() if done_dt_local else fields.Date.context_today(self)

    def write(self, vals):
        # Avoid recursion when we mark pm_completed / hour meter flags internally
        if (
            self.env.context.get("skip_pm_completion")
            or self.env.context.get("skip_hourmeter_update")
            or self.env.context.get("skip_equipment_partner_normalize")
        ):
            return super().write(vals)

        # If equipment is being set/changed, force partner_id to the commercial customer.
        # This guarantees consistent grouping (Customer -> Site) across PM + service tasks.
        if "client_equipment_id" in vals and vals.get("client_equipment_id"):
            eq = self.env["client.equipment"].browse(vals["client_equipment_id"])
            commercial_partner_id = self._get_equipment_commercial_partner_id(eq)
            if commercial_partner_id:
                vals = dict(vals)
                vals["partner_id"] = commercial_partner_id

        # If stage is being changed, validate PM requirements BEFORE closing
        if "stage_id" in vals:
            new_stage = self.env["project.task.type"].browse(vals["stage_id"])
            self._validate_pm_before_close(new_stage=new_stage)

        # Track tasks that might transition to Done (PM completion + hour meter logging)
        pm_candidates = self.filtered(lambda t: t.pm_schedule_id and not t.pm_completed)
        pm_before = {t.id: t._is_done_state() for t in pm_candidates}

        hm_candidates = self.filtered(lambda t: not t.hour_meter_logged and t.client_equipment_id and t.hour_meter_reading is not None)
        hm_before = {t.id: t._is_done_event() for t in hm_candidates}

        res = super().write(vals)

        # Post-write safety net: if user/automation changed partner_id on an equipment-linked task,
        # re-align it back to the commercial customer (without recursion).
        if any(k in vals for k in ("partner_id", "client_equipment_id")):
            for task in self:
                if not task.client_equipment_id:
                    continue
                desired_partner_id = task._get_equipment_commercial_partner_id(task.client_equipment_id)
                if desired_partner_id and task.partner_id.id != desired_partner_id:
                    task.with_context(skip_equipment_partner_normalize=True).write(
                        {"partner_id": desired_partner_id}
                    )

        # Update maintenance schedule only when the task becomes Done (completion-based)
        for task in pm_candidates:
            if not pm_before.get(task.id) and task._is_done_state():
                done_date = task._get_task_done_date()
                task.pm_schedule_id.write({"last_service_date": done_date})
                task.with_context(skip_pm_completion=True).write(
                    {"pm_completed": True, "pm_completed_date": done_date}
                )

                # If customer signature is missing but closure was allowed (override group), log it.
                if not task.customer_signature and self.env.user.has_group(
                    "client_equipment.group_pm_manager_override"
                ):
                    task.message_post(
                        body=(
                            "PM closed with manager override: customer signature was missing."
                        )
                    )

                # If any PM checklist line is Not OK, flag the equipment (do not block closure).
                not_ok_lines = task.pm_checklist_line_ids.filtered(lambda l: l.status == "not_ok")
                if not_ok_lines and task.client_equipment_id:
                    reason = "PM checklist has Not OK items."
                    task.client_equipment_id.write(
                        {
                            "needs_attention": True,
                            "attention_reason": reason,
                            "attention_date": done_date,
                        }
                    )
                    task.message_post(body="PM completed with Not OK checklist items. Equipment flagged for attention.")

        # Safety net: if a PM task is already Done and someone changes checklist lines to Not OK
        # after completion, make sure the equipment gets flagged (per business rule 2=A).
        done_pm_tasks = self.filtered(lambda t: t.pm_schedule_id and t.client_equipment_id and t._is_done_state())
        for task in done_pm_tasks:
            if task.client_equipment_id.needs_attention:
                continue
            if task.pm_checklist_line_ids.filtered(lambda l: l.status == "not_ok"):
                done_date = task.pm_completed_date or task._get_task_done_date()
                task.client_equipment_id.write(
                    {
                        "needs_attention": True,
                        "attention_reason": "PM checklist has Not OK items.",
                        "attention_date": done_date,
                    }
                )
                task.message_post(body="PM checklist contains Not OK items. Equipment flagged for attention.")

        # Hour meter logging + equipment update on first transition to Done
        for task in hm_candidates:
            if hm_before.get(task.id):
                continue
            if not task._is_done_event():
                continue

            equipment = task.client_equipment_id
            reading = task.hour_meter_reading

            if reading is None:
                continue

            current = equipment.hour_meter_current or 0
            if reading < current:
                # Allow closure, ignore the update, and warn (per business rule).
                task.message_post(
                    body=(
                        f"Hour meter update ignored: reading ({reading}) is lower than current equipment hours ({current})."
                    )
                )
                task.with_context(skip_hourmeter_update=True).write({"hour_meter_logged": True})
                continue

            # Create a history log and update the equipment
            self.env["client.equipment.hourmeter.log"].create(
                {
                    "equipment_id": equipment.id,
                    "task_id": task.id,
                    "reading": reading,
                }
            )
            equipment.write(
                {
                    "hour_meter_current": reading,
                    "hour_meter_updated_on": fields.Datetime.now(),
                }
            )
            task.with_context(skip_hourmeter_update=True).write({"hour_meter_logged": True})

        # Keep billing lines aligned when equipment or billing linkage changes.
        if any(k in vals for k in ("client_equipment_id", "sale_line_id", "sale_order_id")):
            self._sync_sale_lines_client_equipment()

        return res

    def _prepare_hourmeter_create_values(self, vals):
        """Prefill hour meter fields for tasks linked to an equipment.

        IMPORTANT: Do NOT override Odoo's internal `_prepare_create_values`, which
        expects a list of dicts.
        """
        if vals.get("client_equipment_id") and "hour_meter_previous" not in vals:
            eq = self.env["client.equipment"].browse(vals["client_equipment_id"])
            vals["hour_meter_previous"] = eq.hour_meter_current or 0
        if vals.get("client_equipment_id") and "hour_meter_reading" not in vals:
            eq = self.env["client.equipment"].browse(vals["client_equipment_id"])
            vals["hour_meter_reading"] = eq.hour_meter_current or 0
        return vals

    def _sync_sale_lines_client_equipment(self):
        """Propagate task.client_equipment_id to linked sale.order.line.

        Equipment Cost (Billed) relies on invoice lines -> sale_line_ids ->
        sale.order.line.client_equipment_id.
        """
        for task in self:
            if not task.client_equipment_id:
                continue

            sale_lines = self.env["sale.order.line"]

            # Primary FSM linkage
            if "sale_line_id" in task._fields and task.sale_line_id:
                sale_lines |= task.sale_line_id

            # Secondary linkage (some flows link SO lines to task_id)
            if "sale_order_id" in task._fields and task.sale_order_id:
                sale_lines |= task.sale_order_id.order_line.filtered(lambda l: getattr(l, "task_id", False) == task)

            if sale_lines:
                sale_lines.write({"client_equipment_id": task.client_equipment_id.id})

    @api.model_create_multi
    def create(self, vals_list):
        prepared = []
        for vals in vals_list:
            vals = dict(vals)
            # Normalize partner_id for equipment-linked tasks at creation time (manual + automated).
            if vals.get("client_equipment_id"):
                eq = self.env["client.equipment"].browse(vals["client_equipment_id"])
                commercial_partner_id = self._get_equipment_commercial_partner_id(eq)
                if commercial_partner_id:
                    vals["partner_id"] = commercial_partner_id

            prepared.append(self._prepare_hourmeter_create_values(vals))
        tasks = super().create(prepared)
        # If billing lines are already linked, keep them aligned.
        tasks._sync_sale_lines_client_equipment()
        return tasks


    # Optional: ensure FSM-created tasks allow adding products/services if the feature exists.
    def _ensure_billable_enabled(self):
        if "allow_billable" in self._fields:
            for task in self:
                if task.allow_billable is False:
                    task.allow_billable = True

    # Parts used on the task (custom, separate from standard FSM products)
    part_line_ids = fields.One2many(
        "project.task.part.line",
        "task_id",
        string="Parts Used",
    )

    def _set_done_qty(self, move_line, qty):
        """Compatibility helper across Odoo versions (qty_done vs quantity vs quantity_done)."""
        if "qty_done" in move_line._fields:
            move_line.qty_done = qty
        elif "quantity" in move_line._fields:
            move_line.quantity = qty
        elif "quantity_done" in move_line._fields:
            move_line.quantity_done = qty
        else:
            raise UserError(
                "Cannot set done quantity on stock move line (no qty_done/quantity field found)."
            )

    def _get_out_picking_type(self):
        """Find an outgoing picking type for the current company."""
        wh = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        )
        if wh and wh.out_type_id:
            return wh.out_type_id

        return self.env["stock.picking.type"].search(
            [("code", "=", "outgoing"), ("company_id", "=", self.env.company.id)], limit=1
        )

    def action_consume_parts(self):
        """Create and validate an outgoing picking from the parts lines not yet consumed."""
        StockPicking = self.env["stock.picking"]
        StockMove = self.env["stock.move"]
        StockMoveLine = self.env["stock.move.line"]

        for task in self:
            lines = task.part_line_ids.filtered(lambda l: not l.consumed)
            if not lines:
                raise UserError("No unconsumed parts on this task.")

            picking_type = task._get_out_picking_type()
            if not picking_type:
                raise UserError(
                    "No outgoing picking type found. Configure a Warehouse in Inventory."
                )

            src_loc = picking_type.default_location_src_id
            dest_loc = picking_type.default_location_dest_id
            if not src_loc or not dest_loc:
                raise UserError(
                    "Picking type locations are not configured (source/destination)."
                )

            picking_vals = {
                "picking_type_id": picking_type.id,
                "location_id": src_loc.id,
                "location_dest_id": dest_loc.id,
                "origin": task.display_name,
                "company_id": task.company_id.id if task.company_id else self.env.company.id,
            }

            if task.client_equipment_id and task.client_equipment_id.partner_id:
                picking_vals["partner_id"] = task.client_equipment_id.partner_id.id

            picking = StockPicking.create(picking_vals)

            for line in lines:
                if line.product_id.tracking != "none" and not line.lot_id:
                    raise UserError(
                        f"Product {line.product_id.display_name} is tracked. Please select Lot/Serial."
                    )

                move_vals = {
                    "picking_id": picking.id,
                    "product_id": line.product_id.id,
                    "product_uom_qty": line.quantity,
                    "product_uom": line.product_uom_id.id,
                    "location_id": src_loc.id,
                    "location_dest_id": dest_loc.id,
                    "company_id": picking.company_id.id,
                    "origin": task.display_name,
                }

                if "description_picking" in StockMove._fields:
                    move_vals["description_picking"] = (
                        f"{task.display_name} - {line.product_id.display_name}"
                    )

                move = StockMove.create(move_vals)

                if line.product_id.tracking != "none":
                    ml_vals = {
                        "picking_id": picking.id,
                        "move_id": move.id,
                        "product_id": line.product_id.id,
                        "product_uom_id": line.product_uom_id.id,
                        "location_id": src_loc.id,
                        "location_dest_id": dest_loc.id,
                        "lot_id": line.lot_id.id,
                    }

                    tmp = StockMoveLine.new(ml_vals)
                    if "qty_done" in tmp._fields:
                        ml_vals["qty_done"] = line.quantity
                    elif "quantity" in tmp._fields:
                        ml_vals["quantity"] = line.quantity
                    elif "quantity_done" in tmp._fields:
                        ml_vals["quantity_done"] = line.quantity

                    StockMoveLine.create(ml_vals)

                line.write({"move_id": move.id, "picking_id": picking.id})

            picking.action_confirm()
            picking.action_assign()

            for ml in picking.move_line_ids:
                done_field = (
                    "qty_done"
                    if "qty_done" in ml._fields
                    else (
                        "quantity"
                        if "quantity" in ml._fields
                        else (
                            "quantity_done"
                            if "quantity_done" in ml._fields
                            else None
                        )
                    )
                )
                current_done = getattr(ml, done_field) if done_field else 0
                if not current_done:
                    qty = (
                        getattr(ml, "reserved_uom_qty", 0)
                        or getattr(ml, "product_uom_qty", 0)
                        or 0
                    )
                    if qty:
                        task._set_done_qty(ml, qty)

            if hasattr(picking, "button_validate"):
                picking.button_validate()
            else:
                picking._action_done()

            lines.write({"consumed": True})

        return True


    def _get_job_confirmation_lines(self):
        """Return materials/services lines for the Job Confirmation report.

        This is UI/report-only. It does not create invoices or alter SOs.
        It tries to read standard Odoo T&M sources when installed (sale_project),
        and falls back gracefully when not available.
        """
        self.ensure_one()
        lines = []

        # 1) If Sales Project is installed, task may be linked to a sale order / order lines
        SaleOrderLine = self.env.get("sale.order.line")
        if SaleOrderLine and "sale_order_id" in self._fields:
            so = self.sale_order_id
            if so:
                solines = so.order_line
                # If order lines have task_id, filter to this task
                if "task_id" in SaleOrderLine._fields:
                    solines = solines.filtered(lambda l: l.task_id.id == self.id)
                for l in solines:
                    qty = getattr(l, "product_uom_qty", 0.0)
                    uom = l.product_uom.name if getattr(l, "product_uom", False) else ""
                    name = l.name or (l.product_id.display_name if getattr(l, "product_id", False) else "")
                    lines.append({"name": name, "qty": qty, "uom": uom})

        # 2) Fallback: if a single sale_line_id exists (service line), include it
        if not lines and "sale_line_id" in self._fields and self.sale_line_id:
            l = self.sale_line_id
            qty = getattr(l, "product_uom_qty", 0.0)
            uom = l.product_uom.name if getattr(l, "product_uom", False) else ""
            name = l.name or (l.product_id.display_name if getattr(l, "product_id", False) else "")
            lines.append({"name": name, "qty": qty, "uom": uom})

        # 3) Fallback: old custom part lines (if present)
        if not lines and "part_line_ids" in self._fields:
            for pl in self.part_line_ids:
                uom = pl.uom_id.name if getattr(pl, "uom_id", False) else ""
                lines.append({"name": pl.product_id.display_name if pl.product_id else "", "qty": pl.qty or 0.0, "uom": uom})

        return lines