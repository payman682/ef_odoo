# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError


class ClientEquipmentDemoCleanupWizard(models.TransientModel):
    _name = "client.equipment.demo.cleanup.wizard"
    _description = "Client Equipment Demo Data Cleanup"

    confirm = fields.Boolean(
        string="I understand this will remove demo data",
        default=False,
        help=(
            "This wizard deletes demo PM checklist templates/lines/sections and removes the demo category when possible. "
            "Only records that were created from this module's XMLIDs are targeted. "
            "If a record is still referenced, it will be archived instead of deleted."
        ),
    )

    def _archive_if_possible(self, record):
        """Archive a record if it supports 'active'. Return True if archived."""
        if record and record.exists() and "active" in record._fields:
            record.write({"active": False})
            return True
        return False

    def _get_demo_records(self):
        """Return demo records shipped by this module using ir.model.data.

        We only target records that:
        - have an XMLID (ir.model.data)
        - belong to module 'client_equipment'
        - are one of the demo business models we shipped as sample data

        User-created records do not have XMLIDs and are therefore safe.
        """
        IrModelData = self.env["ir.model.data"]
        demo_models = [
            "client.equipment.pm.checklist.template",
            "client.equipment.pm.checklist.template.line",
            "client.equipment.pm.checklist.section",
            "client.equipment.category",
        ]
        imd = IrModelData.search([
            ("module", "=", "client_equipment"),
            ("model", "in", demo_models),
        ])

        records = []
        for rec in imd:
            obj = self.env[rec.model].browse(rec.res_id)
            if obj.exists():
                records.append(obj)
        return records

    def action_cleanup_strict(self):
        self.ensure_one()
        if not self.confirm:
            raise UserError(_("Please tick the confirmation checkbox before running cleanup."))

        refs = self._get_demo_records()
        if not refs:
            raise UserError(_("No demo records were found (nothing to clean)."))

        templates = [r for r in refs if r._name == "client.equipment.pm.checklist.template"]
        template_lines = [r for r in refs if r._name == "client.equipment.pm.checklist.template.line"]
        sections = [r for r in refs if r._name == "client.equipment.pm.checklist.section"]
        categories = [r for r in refs if r._name == "client.equipment.category"]

        deleted = 0
        archived = 0
        skipped = 0

        # 1) Delete template lines first, fallback to archive if needed
        for line in template_lines:
            try:
                line.unlink()
                deleted += 1
            except Exception:
                if self._archive_if_possible(line):
                    archived += 1
                else:
                    skipped += 1

        # 2) Delete templates, fallback to archive if referenced
        for tpl in templates:
            try:
                tpl.unlink()
                deleted += 1
            except Exception:
                if self._archive_if_possible(tpl):
                    archived += 1
                else:
                    skipped += 1

        # 3) Delete sections; if still referenced, archive instead
        for sec in sections:
            try:
                sec.unlink()
                deleted += 1
            except Exception:
                if self._archive_if_possible(sec):
                    archived += 1
                else:
                    skipped += 1

        # 4) Delete categories; if still referenced, archive instead
        for cat in categories:
            try:
                cat.unlink()
                deleted += 1
            except Exception:
                if self._archive_if_possible(cat):
                    archived += 1
                else:
                    skipped += 1

        msg = _("Demo cleanup completed. Deleted: %(d)s, Archived: %(a)s, Skipped: %(s)s") % {
            "d": deleted,
            "a": archived,
            "s": skipped,
        }
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Cleanup finished"),
                "message": msg,
                "type": "success" if skipped == 0 else "warning",
                "sticky": False,
            },
        }
