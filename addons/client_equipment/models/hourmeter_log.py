from odoo import fields, models


class ClientEquipmentHourmeterLog(models.Model):
    _name = "client.equipment.hourmeter.log"
    _description = "Equipment Hour Meter Log"
    _order = "date desc, id desc"

    equipment_id = fields.Many2one(
        "client.equipment",
        string="Equipment",
        required=True,
        ondelete="cascade",
        index=True,
    )
    task_id = fields.Many2one(
        "project.task",
        string="Task",
        ondelete="set null",
        index=True,
    )
    date = fields.Datetime(string="Date", required=True, default=lambda self: fields.Datetime.now(), index=True)
    reading = fields.Integer(string="Hour Meter Reading", required=True, index=True)
    user_id = fields.Many2one("res.users", string="Recorded By", default=lambda self: self.env.user, readonly=True)
    note = fields.Char(string="Note")
