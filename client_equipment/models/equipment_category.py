from odoo import fields, models

class ClientEquipmentCategory(models.Model):
    _name = "client.equipment.category"
    _description = "Equipment Category"
    _order = "name"

    name = fields.Char(required=True, index=True)
    active = fields.Boolean(default=True)
