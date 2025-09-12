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
python -m cli.main down my-server
python -m cli.main status my-server
python -m cli.main scale my-server 3
python -m cli.main list
python -m cli.main metrics



# View all apps
python view_docker_db.py apps

# View summary
python view_docker_db.py summary  

# View instances
python view_docker_db.py instances

# View events
python view_docker_db.py events

# View scaling history
python view_docker_db.py scaling


sqlite3 data/autoscaler.db "DELETE FROM scaling_history; DELETE FROM events; DELETE FROM instances; DELETE FROM apps; VACUUM;"

(1)TODO: if name of the container is conflicting, ask to delete(manually) and run again

(2)TODO: add 'docter' command for dependency check

(3)TODO: check if the image exists locally/remotely before registering

(4)TODO: auto heal dead containers without loosing any req/res

(5)TODO: state not saving in sqlite rn
