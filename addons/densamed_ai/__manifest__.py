{
    'name': 'DensaMed AI Forecast Demo',
    'version': '17.0.1.0.0',
    'category': 'Inventory',
    'summary': 'Academic seven-day demand forecasting and replenishment demo',
    'license': 'LGPL-3',
    'depends': ['densamed_sale', 'purchase'],
    'external_dependencies': {'python': ['sklearn', 'joblib']},
    'data': [
        'security/ir.model.access.csv',
        'security/rules.xml',
        'views/forecast_views.xml',
    ],
    'application': True,
    'installable': True,
}
