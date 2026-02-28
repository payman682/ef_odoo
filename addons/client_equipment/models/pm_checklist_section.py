# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ClientEquipmentPMChecklistSection(models.Model):
    _name = "client.equipment.pm.checklist.section"
    _description = "PM Checklist Section"
    _order = "sequence, name, id"

    name = fields.Char(required=True, translate=False)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    category_id = fields.Many2one(
        "client.equipment.category",
        string="Equipment Type",
        ondelete="cascade",
        help="If set, this section is only available for this equipment type. "
             "If empty, it is global and available for all equipment types.",
    )

    # Odoo 19+: SQL constraints are defined via models.Constraint attributes
    _section_name_category_uniq = models.Constraint(
        "UNIQUE(name, category_id)",
        "Section name must be unique per Equipment Type.",
    )

    @api.model
    def _legacy_section_label_map(self):
        return {
            "general": "General Information",
            "safety": "Safety & Compliance",
            "engine": "Engine / Power Source",
            "hydraulic": "Hydraulic System",
            "mast": "Mast, Forks & Attachments",
            "brakes": "Brakes & Steering",
            "tires": "Tires & Wheels",
            "electrical": "Electrical System",
            "final": "Final Sign-Off",
        }

    def _ensure_section(self, name, category_id=False):
        domain = [("name", "=", name), ("category_id", "=", category_id or False)]
        sec = self.search(domain, limit=1)
        if sec:
            return sec
        return self.create({"name": name, "category_id": category_id or False})

    def init(self):
        """Migrate legacy Selection section -> Many2one section_id.

        Safe + idempotent:
        - Only runs if legacy column exists
        - Only fills section_id when empty
        - Creates section records as needed
        """
        cr = self.env.cr

        def _has_column(table, column):
            cr.execute(
                """
                SELECT 1
                  FROM information_schema.columns
                 WHERE table_name=%s AND column_name=%s
                 LIMIT 1
                """,
                (table, column),
            )
            return bool(cr.fetchone())

        tpl_table = "client_equipment_pm_checklist_template_line"
        task_table = "project_task_pm_checklist_line"

        legacy_map = self._legacy_section_label_map()

        # Template lines: create per equipment type sections (category-specific)
        if _has_column(tpl_table, "section") and _has_column(tpl_table, "section_id"):
            cr.execute(
                """
                SELECT l.template_id, l.section
                  FROM client_equipment_pm_checklist_template_line l
                 WHERE l.section_id IS NULL
                   AND l.section IS NOT NULL
                """
            )
            rows = cr.fetchall()
            if rows:
                template_ids = list({r[0] for r in rows if r[0]})
                if template_ids:
                    templates = self.env["client.equipment.pm.checklist.template"].browse(template_ids).exists()
                    cat_by_tpl = {t.id: (t.category_id.id if t.category_id else False) for t in templates}
                else:
                    cat_by_tpl = {}

                # Build cache for sections
                cache = {}
                for tpl_id, key in rows:
                    if not key:
                        continue
                    cat_id = cat_by_tpl.get(tpl_id) or False
                    label = legacy_map.get(key, key)
                    cache_key = (label, cat_id)
                    if cache_key not in cache:
                        cache[cache_key] = self._ensure_section(label, cat_id)

                # Update rows
                for tpl_id, key in rows:
                    if not key:
                        continue
                    cat_id = cat_by_tpl.get(tpl_id) or False
                    label = legacy_map.get(key, key)
                    sec = cache.get((label, cat_id))
                    if sec:
                        cr.execute(
                            """
                            UPDATE client_equipment_pm_checklist_template_line
                               SET section_id=%s
                             WHERE template_id=%s
                               AND section=%s
                               AND section_id IS NULL
                            """,
                            (sec.id, tpl_id, key),
                        )

        # Task lines: create GLOBAL sections (category empty)
        if _has_column(task_table, "section") and _has_column(task_table, "section_id"):
            cr.execute(
                """
                SELECT DISTINCT section
                  FROM project_task_pm_checklist_line
                 WHERE section_id IS NULL
                   AND section IS NOT NULL
                """
            )
            keys = [r[0] for r in cr.fetchall() if r and r[0]]
            if keys:
                cache = {}
                for key in keys:
                    label = legacy_map.get(key, key)
                    cache[key] = self._ensure_section(label, False)
                for key, sec in cache.items():
                    cr.execute(
                        """
                        UPDATE project_task_pm_checklist_line
                           SET section_id=%s
                         WHERE section=%s
                           AND section_id IS NULL
                        """,
                        (sec.id, key),
                    )
