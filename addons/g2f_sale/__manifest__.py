# Copyright 2020 FoxCarlos
# License AGPL-3 or later (http://www.gnu.org/licenses/agpl).

{
    'name': "G2F Sale",
    'summary': """
        Go2future Sale""",
    'author': "FoxCarlos, Odoo Community Association (OCA)",
    'website': "",
    'category': 'Sales',
    'license': 'LGPL-3',
    'version': '12.0.1.0.0',
    'depends': ['sale_management'],
    'data': [
        'views/product_template.xml',
        'security/ir.model.access.csv',
    ],
    'demo': [
    ],
    'installable': True,
    'auto_install': False,
    'application': True,
}
