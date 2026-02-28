from odoo import api, fields, models
from odoo.exceptions import ValidationError

class ProjectTaskPartLine(models.Model):
    _name = "project.task.part.line"
    _description = "Task Parts Used"
    _order = "id desc"

    task_id = fields.Many2one("project.task", required=True, ondelete="cascade", index=True)
    product_id = fields.Many2one("product.product", required=True, domain=[("type", "in", ["product", "consu"])])
    product_uom_id = fields.Many2one("uom.uom", string="UoM", required=True)
    quantity = fields.Float(required=True, default=1.0)
    lot_id = fields.Many2one("stock.lot", string="Lot/Serial", domain="[('product_id', '=', product_id)]")

    consumed = fields.Boolean(default=False, readonly=True)
    picking_id = fields.Many2one("stock.picking", readonly=True, ondelete="set null")
    move_id = fields.Many2one("stock.move", readonly=True, ondelete="set null")

    @api.onchange("product_id")
    def _onchange_product_id(self):
        for line in self:
            if line.product_id:
                line.product_uom_id = line.product_id.uom_id

    @api.constrains("quantity")
    def _check_qty(self):
        for line in self:
            if line.quantity <= 0:
                raise ValidationError("Quantity must be greater than 0.")
