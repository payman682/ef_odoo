# -*- coding: utf-8 -*-

from odoo import api, fields, models


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    client_equipment_id = fields.Many2one(
        "client.equipment",
        string="Equipment",
        index=True,
        help="The equipment this line (labor or parts) is billed against.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        # Best effort: if this SO is generated from an FSM task, make sure ALL lines
        # inherit the same equipment so invoice + reports can work.
        lines._ce_apply_default_equipment()
        return lines

    def write(self, vals):
        res = super().write(vals)
        # If caller didn't explicitly set equipment, try to backfill from task / other lines.
        if "client_equipment_id" not in vals:
            self._ce_apply_default_equipment()
        return res

    def _ce_apply_default_equipment(self):
        for line in self:
            if line.client_equipment_id:
                continue

            order = line.order_id
            equipment = False

            # 1) From FSM task linked on the sale order (different enterprise variants).
            task = getattr(order, "source_task_id", False) or getattr(order, "task_id", False) or getattr(order, "fsm_task_id", False)
            if task and hasattr(task, "client_equipment_id"):
                equipment = task.client_equipment_id

            # 2) From any other line on the same order.
            if not equipment and order:
                equipment = order.order_line.filtered("client_equipment_id")[:1].client_equipment_id

            if equipment:
                line.client_equipment_id = equipment

    def _prepare_invoice_line(self, **optional_values):
        vals = super()._prepare_invoice_line(**optional_values)
        if self.client_equipment_id:
            vals["client_equipment_id"] = self.client_equipment_id.id
        return vals
