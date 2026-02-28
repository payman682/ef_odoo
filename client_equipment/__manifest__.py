# -*- coding: utf-8 -*-
{
    'name': 'Client Equipment PRO (Forklift Service)',
    'version': '19.0.8.15.0',
    'category': 'Services',
    'summary': 'Installed base + Sites + Parts consumption + Warranty + PM scheduler + Technician view + Service report PDF',
    'author': 'Forklift Plus',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'project', 'stock', 'industry_fsm', 'sale', 'account', 'hr_timesheet'],
    'data': ['security/groups.xml', 'security/ir.model.access.csv', 'data/cron.xml', 'data/sequence.xml', 'views/menu_root.xml', 'views/client_equipment_views.xml', 'views/ir_attachment_views.xml', 'views/client_equipment_maintenance_views.xml', 'views/category_views.xml', 'views/manufacturer_views.xml', 'views/project_task_views.xml', 'views/sale_order_views.xml', 'views/technician_views.xml', 'views/technician_history_wizard_views.xml', 'views/pm_checklist_views.xml', 'views/pm_checklist_section_views.xml', 'views/pm_wizard_views.xml', 'views/serial_uniqueness_wizard_views.xml', 'views/demo_cleanup_wizard_views.xml', 'views/equipment_invoice_cost_views.xml', 'views/customer_service_revenue_views.xml', 'views/equipment_service_history_views.xml', 'views/menu_action_aliases.xml', 'views/equipment_reports_menus.xml', 'report/service_report.xml', 'report/service_report_template.xml', 'report/job_confirmation_template.xml', 'report/job_confirmation_report.xml', 'views/menus.xml', 'views/equipment_reports_phase1.xml'],
    'demo': [],
    'application': True,
    'installable': True,
    'post_init_hook': 'post_init_hook'
}
