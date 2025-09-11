POST /api/v1/apps - Register applications
POST /api/v1/apps/{app_name}/start - Start apps
POST /api/v1/apps/{app_name}/stop - Stop apps
POST /api/v1/apps/{app_name}/scale - Scale apps
GET /api/v1/apps/{app_name} - Get app status
GET /api/v1/apps - List all apps
GET /health - Health check


Python version == 3.13.5

python -m cli.main register my-app.yml
python -m cli.main up my-app
python -m cli.main status my-app
python -m cli.main scale my-app 3
python -m cli.main list
python -m cli.main metrics
