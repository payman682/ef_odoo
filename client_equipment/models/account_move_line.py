# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    # --- Equipment link (Billed Cost report) ---
    # IMPORTANT: Do NOT depend on sale.order.line.task_id (it is not present unless extra modules are installed).
    # We compute from sale_line_ids -> sale.order.line.client_equipment_id (our module adds this field).
    client_equipment_id = fields.Many2one(
        comodel_name="client.equipment",
        string="Client Equipment",
        compute="_compute_client_equipment_id",
        store=True,
        index=True,
        readonly=False,  # allow manual correction if needed
    )

    @api.depends(
        "sale_line_ids",
        "sale_line_ids.client_equipment_id",
        "sale_line_ids.order_id.equipment_id",
        "move_id.invoice_origin",
    )
    def _compute_client_equipment_id(self):
        """Compute equipment for invoice lines.

        Priority:
        1) Explicit equipment on sale.order.line (best)
        2) Fallback to sale.order.equipment_id (computed from source task)
        3) Fallback to invoice_origin -> sale.order.name (last resort)
        """
        SaleOrder = self.env["sale.order"]
        for line in self:
            eq_id = False

            # 1) From linked sale lines (preferred)
            if getattr(line, "sale_line_ids", False):
                eq_id = (line.sale_line_ids.mapped("client_equipment_id")[:1].id) or False

                # 2) Fallback from the sale order if SOL wasn't backfilled
                if not eq_id:
                    eq_id = (line.sale_line_ids.mapped("order_id.equipment_id")[:1].id) or False

            # 3) Last resort: invoice_origin holds SO name in many flows
            if not eq_id and line.move_id and line.move_id.invoice_origin:
                order = SaleOrder.search([("name", "=", line.move_id.invoice_origin)], limit=1)
                if order and getattr(order, "equipment_id", False):
                    eq_id = order.equipment_id.id

            line.client_equipment_id = eq_id

    # --- Cost classification fields ---
    ce_cost_bucket = fields.Selection(
        selection=[
            ("labor", "Labor"),
            ("parts", "Parts"),
            ("other", "Other"),
        ],
        string="Bucket",
        compute="_compute_ce_cost_fields",
        store=True,
        index=True,
    )
    ce_labor_amount = fields.Monetary(
        string="Labor (Subtotal)",
        currency_field="currency_id",
        compute="_compute_ce_cost_fields",
        store=True,
    )
    ce_parts_amount = fields.Monetary(
        string="Parts (Subtotal)",
        currency_field="currency_id",
        compute="_compute_ce_cost_fields",
        store=True,
    )

    ce_labor_total = fields.Monetary(
        string="Labor (Total)",
        currency_field="currency_id",
        compute="_compute_ce_cost_fields",
        store=True,
    )
    ce_parts_total = fields.Monetary(
        string="Parts (Total)",
        currency_field="currency_id",
        compute="_compute_ce_cost_fields",
        store=True,
    )

    @api.depends("price_subtotal", "price_total", "product_id", "display_type")
    def _compute_ce_cost_fields(self):
        for line in self:
            bucket = "other"
            labor = 0.0
            parts = 0.0
            labor_total = 0.0
            parts_total = 0.0

            if line.display_type:
                line.ce_cost_bucket = bucket
                line.ce_labor_amount = labor
                line.ce_parts_amount = parts
                line.ce_labor_total = labor_total
                line.ce_parts_total = parts_total
                continue

            prod = line.product_id
            if prod:
                detailed_type = getattr(prod, "detailed_type", False) or getattr(prod, "type", False)
                if detailed_type == "service":
                    bucket = "labor"
                    labor = line.price_subtotal or 0.0
                    labor_total = getattr(line, "price_total", 0.0) or 0.0
                else:
                    bucket = "parts"
                    parts = line.price_subtotal or 0.0
                    parts_total = getattr(line, "price_total", 0.0) or 0.0

            line.ce_cost_bucket = bucket
            line.ce_labor_amount = labor
            line.ce_parts_amount = parts
            line.ce_labor_total = labor_total
            line.ce_parts_total = parts_total
