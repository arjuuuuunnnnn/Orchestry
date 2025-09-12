POST /api/v1/apps/register - Register applications

POST /api/v1/apps/{app_name}/start - Start apps

POST /api/v1/apps/{app_name}/stop - Stop apps

POST /api/v1/apps/{app_name}/scale - Scale apps

GET /api/v1/apps/{app_name} - Get app status

GET /api/v1/apps - List all apps

GET /health


Python version == 3.13.5

python -m cli.main register my-server.yml
python -m cli.main up my-server
python -m cli.main status my-server
python -m cli.main scale my-server 3
python -m cli.main list
python -m cli.main metrics



python view_db.py

python view_db.py summary
python view_db.py apps
python view_db.py instances
python view_db.py events
python view_db.py scaling


sqlite3 data/autoscaler.db "DELETE FROM scaling_history; DELETE FROM events; DELETE FROM instances; DELETE FROM apps; VACUUM;"

(1)TODO: if name of the container is conflicting, ask to delete(manually) and run again

(2)TODO: add 'docter' command for dependency check

(3)TODO: check if the image exists locally/remotely before registering