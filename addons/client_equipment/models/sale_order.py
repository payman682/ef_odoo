# -*- coding: utf-8 -*-
from odoo import api, fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    source_task_id = fields.Many2one(
        comodel_name="project.task",
        string="Source Task",
        compute="_compute_source_task_id",
        readonly=True,
        help="FSM/Project task related to this Sales Order. Filled automatically.",
    )

    equipment_id = fields.Many2one(
        comodel_name="client.equipment",
        string="Equipment",
        compute="_compute_equipment_id",
        readonly=True,
        help="Derived from Source Task -> Client Equipment. Used for reporting/traceability.",
    )

    def _ce_find_related_task(self):
        """Best-effort resolver for the task linked to this sale order.

        We keep it defensive because Enterprise flows differ (FSM, Project, Sale).
        """
        Task = self.env["project.task"]
        # Some Enterprise variants have direct links on sale.order
        for order in self:
            task = False

            # 1) Native/enterprise direct fields if present
            for fname in ("task_id", "fsm_task_id"):
                if fname in order._fields and getattr(order, fname):
                    task = getattr(order, fname)
                    break
            if task:
                yield order, task
                continue

            # 2) Task has a direct link to sale order (if present in this DB)
            if "sale_order_id" in Task._fields:
                task = Task.search([("sale_order_id", "=", order.id)], limit=1, order="id asc")
                if task:
                    yield order, task
                    continue

            # 3) Task linked via sale_line_id -> order (common in project/sale integration)
            if "sale_line_id" in Task._fields:
                task = Task.search([("sale_line_id.order_id", "=", order.id)], limit=1, order="id asc")
                if task:
                    yield order, task
                    continue

            yield order, False

    @api.depends("order_line")
    def _compute_source_task_id(self):
        # Note: deps are approximate; we intentionally compute dynamically for correctness.
        for order, task in self._ce_find_related_task():
            order.source_task_id = task.id if task else False

    @api.depends("source_task_id")
    def _compute_equipment_id(self):
        for order in self:
            task = order.source_task_id
            eq = False
            if task and "client_equipment_id" in task._fields:
                eq = task.client_equipment_id.id or False
            order.equipment_id = eq
