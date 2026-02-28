from odoo import api, fields, models


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    client_equipment_id = fields.Many2one(
        "client.equipment",
        string="Equipment",
        index=True,
        ondelete="cascade",
    )

    @api.model_create_multi
    def create(self, vals_list):
        # Keep standard res_model/res_id in sync for access rules and consistency.
        for vals in vals_list:
            eq_id = vals.get("client_equipment_id")
            if eq_id and not vals.get("res_model"):
                vals["res_model"] = "client.equipment"
                vals["res_id"] = eq_id
        return super().create(vals_list)

    def write(self, vals):
        res = super().write(vals)
        if "client_equipment_id" in vals:
            for att in self:
                if att.client_equipment_id:
                    # ensure linkage remains consistent
                    if att.res_model != "client.equipment" or att.res_id != att.client_equipment_id.id:
                        super(IrAttachment, att).write({
                            "res_model": "client.equipment",
                            "res_id": att.client_equipment_id.id,
                        })
        return res
