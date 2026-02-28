Incremental patch for Equipment Cost (Billed)

What it fixes:
- Adds account.move.line.client_equipment_id (computed/stored) from sale_line_ids.client_equipment_id
- Keeps ce_cost_bucket / ce_labor_amount / ce_parts_amount computed/stored
- Fixes view type for Odoo 19: use <list> (not <tree>)
- Adds a valid search view + safe Month group_by using line date

Apply:
Copy/merge into custom_addons/client_equipment/:
- models/account_move_line.py (replace your file)
- views/equipment_invoice_cost_views.xml (replace your file)
If your models/__init__.py already imports account_move_line, keep yours.

Then upgrade Client Equipment module.
