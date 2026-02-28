# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ClientEquipmentPMChecklistTemplate(models.Model):
    _name = "client.equipment.pm.checklist.template"
    _description = "PM Checklist Template"
    _order = "name"

    name = fields.Char(required=True)
    category_id = fields.Many2one(
        "client.equipment.category",
        string="Equipment Type",
        required=True,
        ondelete="restrict",
        help="The checklist template is applicable only to this equipment type/category.",
    )
    active = fields.Boolean(default=True)
    line_ids = fields.One2many(
        "client.equipment.pm.checklist.template.line",
        "template_id",
        string="Checklist Items",
        copy=True,
    )


class ClientEquipmentPMChecklistTemplateLine(models.Model):
    _name = "client.equipment.pm.checklist.template.line"
    _description = "PM Checklist Template Line"
    _order = "sequence, id"

    template_id = fields.Many2one(
        "client.equipment.pm.checklist.template",
        required=True,
        ondelete="cascade",
    )
    template_category_id = fields.Many2one(
        related="template_id.category_id",
        store=True,
        readonly=True,
    )

    sequence = fields.Integer(default=10)

    section_id = fields.Many2one(
        "client.equipment.pm.checklist.section",
        string="Section",
        required=True,
        ondelete="restrict",
    )

    name = fields.Char(string="Item", required=True)


class ProjectTaskPMChecklistLine(models.Model):
    _name = "project.task.pm.checklist.line"
    _description = "PM Checklist Line"
    _order = "sequence, id"

    task_id = fields.Many2one("project.task", required=True, ondelete="cascade", index=True)
    task_equipment_category_id = fields.Many2one(
        related="task_id.client_equipment_id.category_id",
        store=True,
        readonly=True,
    )

    sequence = fields.Integer(default=10)

    section_id = fields.Many2one(
        "client.equipment.pm.checklist.section",
        string="Section",
        required=True,
        ondelete="restrict",
    )

    name = fields.Char(string="Item", required=True)

    status = fields.Selection(
        [
            ("ok", "OK"),
            ("not_ok", "Not OK"),
            ("na", "N/A"),
        ],
        default="ok",
        required=True,
    )
    remarks = fields.Char()

    def _flag_equipment_if_needed(self):
        """If checklist contains Not OK on a completed PM task, flag the equipment.

        This is a post-completion safety net because checklist lines can be edited
        after the task is already Done.
        """
        for line in self:
            task = line.task_id
            if not task or not task.pm_schedule_id or not task.client_equipment_id:
                continue
            # Only flag if task is already Done/Closed.
            if not task._is_done_event():
                continue
            if line.status != "not_ok":
                continue
            eq = task.client_equipment_id
            if eq.needs_attention:
                continue
            done_date = task.pm_completed_date or task._get_task_done_date()
            eq.write(
                {
                    "needs_attention": True,
                    "attention_reason": "PM checklist has Not OK items.",
                    "attention_date": done_date,
                }
            )
            task.message_post(body="PM checklist contains Not OK items. Equipment flagged for attention.")

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._flag_equipment_if_needed()
        return records

    def write(self, vals):
        res = super().write(vals)
        if "status" in vals:
            self._flag_equipment_if_needed()
        return res


class ProjectTask(models.Model):
    _inherit = "project.task"

    pm_checklist_line_ids = fields.One2many(
        "project.task.pm.checklist.line", "task_id", string="PM Checklist"
    )

    def _pm_prepare_checklist_commands(self, template):
        """Return O2M commands to create checklist lines from a template."""
        if not template:
            return []
        commands = []
        for line in template.line_ids.sorted(lambda l: (l.sequence, l.id)):
            commands.append(
                (
                    0,
                    0,
                    {
                        "sequence": line.sequence,
                        "section_id": line.section_id.id,
                        "name": line.name,
                        "status": "ok",
                        "remarks": "",
                    },
                )
            )
        return commands
