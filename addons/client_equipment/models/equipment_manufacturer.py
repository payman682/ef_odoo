from odoo import models, fields

class ClientEquipmentManufacturer(models.Model):
    _name = "client.equipment.manufacturer"
    _description = "Equipment Manufacturer"
    _order = "name"

    name = fields.Char(required=True)
    logo = fields.Image(string="Logo", help="Manufacturer logo.")
    active = fields.Boolean(default=True)
