# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class ClientEquipmentSerialUniquenessWizard(models.TransientModel):
    _name = "client.equipment.serial.uniqueness.wizard"
    _description = "Serial Uniqueness Enforcement"

    duplicates_with_site_count = fields.Integer(string="Duplicate Groups (With Site)", compute="_compute_counts")
    duplicates_no_site_count = fields.Integer(string="Duplicate Groups (No Site)", compute="_compute_counts")

    def _get_duplicate_groups(self):
        """Return (with_site_groups, no_site_groups) as list of dicts from read_group."""
        Equipment = self.env["client.equipment"].with_context(active_test=False)

        base_domain = [("serial_number", "!=", False), ("partner_id", "!=", False)]

        with_site_groups = Equipment.read_group(
            domain=base_domain + [("site_contact_id", "!=", False)],
            fields=["partner_id", "site_contact_id", "serial_number"],
            groupby=["partner_id", "site_contact_id", "serial_number"],
            lazy=False,
        )
        with_site_groups = [g for g in with_site_groups if g.get("__count", 0) > 1]

        no_site_groups = Equipment.read_group(
            domain=base_domain + [("site_contact_id", "=", False)],
            fields=["partner_id", "serial_number"],
            groupby=["partner_id", "serial_number"],
            lazy=False,
        )
        no_site_groups = [g for g in no_site_groups if g.get("__count", 0) > 1]

        return with_site_groups, no_site_groups

    @api.depends_context("uid")
    def _compute_counts(self):
        for wiz in self:
            with_site, no_site = wiz._get_duplicate_groups()
            wiz.duplicates_with_site_count = len(with_site)
            wiz.duplicates_no_site_count = len(no_site)

    def _duplicate_ids_from_groups(self, groups, with_site):
        Equipment = self.env["client.equipment"].with_context(active_test=False)
        ids = set()
        for g in groups:
            partner_id = g["partner_id"][0] if g.get("partner_id") else False
            serial = g.get("serial_number")
            if not partner_id or not serial:
                continue
            domain = [("partner_id", "=", partner_id), ("serial_number", "=", serial)]
            if with_site:
                site_id = g["site_contact_id"][0] if g.get("site_contact_id") else False
                if not site_id:
                    continue
                domain.append(("site_contact_id", "=", site_id))
            else:
                domain.append(("site_contact_id", "=", False))
            ids.update(Equipment.search(domain).ids)
        return list(ids)

    def action_show_duplicates_with_site(self):
        self.ensure_one()
        with_site, _no_site = self._get_duplicate_groups()
        ids = self._duplicate_ids_from_groups(with_site, with_site=True)
        return {
            "type": "ir.actions.act_window",
            "name": _("Duplicate Serials (With Site)"),
            "res_model": "client.equipment",
            "view_mode": "tree,form",
            "domain": [("id", "in", ids)],
            "target": "current",
        }

    def action_show_duplicates_no_site(self):
        self.ensure_one()
        _with_site, no_site = self._get_duplicate_groups()
        ids = self._duplicate_ids_from_groups(no_site, with_site=False)
        return {
            "type": "ir.actions.act_window",
            "name": _("Duplicate Serials (No Site)"),
            "res_model": "client.equipment",
            "view_mode": "tree,form",
            "domain": [("id", "in", ids)],
            "target": "current",
        }

    def action_enable_enforcement(self):
        self.ensure_one()

        with_site, no_site = self._get_duplicate_groups()
        if with_site or no_site:
            raise UserError(
                _(
                    "You still have duplicate serial numbers.\n\n"
                    "Duplicate groups (with site): %(with_site)s\n"
                    "Duplicate groups (no site): %(no_site)s\n\n"
                    "Please fix/merge/archive duplicates first, then try again."
                )
                % {"with_site": len(with_site), "no_site": len(no_site)}
            )

        # Drop old global constraint if it exists (from earlier versions)
        self.env.cr.execute(
            "ALTER TABLE client_equipment DROP CONSTRAINT IF EXISTS client_equipment_serial_unique"
        )

        # Create partial unique indexes for C2 behavior
        self.env.cr.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS client_equipment_uniq_serial_with_site_idx
            ON client_equipment (partner_id, site_contact_id, serial_number)
            WHERE site_contact_id IS NOT NULL
              AND partner_id IS NOT NULL
              AND serial_number IS NOT NULL
            """
        )
        self.env.cr.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS client_equipment_uniq_serial_no_site_idx
            ON client_equipment (partner_id, serial_number)
            WHERE site_contact_id IS NULL
              AND partner_id IS NOT NULL
              AND serial_number IS NOT NULL
            """
        )

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Serial Uniqueness Enabled"),
                "message": _("Database enforcement enabled successfully."),
                "sticky": False,
            },
        }
