# -*- coding: utf-8 -*-
from odoo import api, SUPERUSER_ID

REL_TABLE = "client_equipment_ir_attachment_rel"

def post_init_hook(env):
    """Migrate legacy Many2many attachment links to the safer Many2one linkage.

    Odoo 19 calls post_init_hook with an Environment (env).

    Older versions linked equipment to attachments via a custom rel table, which could
    create attachments without consistent res_model/res_id. We keep the old field for
    backward compatibility, but going forward we rely on ir.attachment.client_equipment_id.
    """
    # In Odoo 19, Environment itself has no sudo(); elevate by rebuilding env as superuser.
    env = api.Environment(env.cr, SUPERUSER_ID, dict(env.context))
    cr = env.cr

    # If the rel table doesn't exist (fresh install), nothing to migrate.
    cr.execute("SELECT to_regclass(%s)", (REL_TABLE,))
    reg = cr.fetchone()
    if not reg or not reg[0]:
        return

    cr.execute(f"SELECT equipment_id, attachment_id FROM {REL_TABLE}")
    rows = cr.fetchall()
    if not rows:
        return

    Attachment = env["ir.attachment"].with_context(active_test=False)
    for equipment_id, attachment_id in rows:
        att = Attachment.browse(attachment_id)
        if not att.exists():
            continue
        # Idempotent: do not override if already linked.
        if not att.client_equipment_id:
            att.write({
                "client_equipment_id": equipment_id,
                "res_model": "client.equipment",
                "res_id": equipment_id,
            })
