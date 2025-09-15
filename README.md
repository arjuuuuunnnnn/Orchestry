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

# View database summary  
python view_docker_db.py summary

# View container instances
python view_docker_db.py instances

# View system events
python view_docker_db.py events

# View scaling history
python view_docker_db.py scaling


# Filter events by app
python view_docker_db.py events --app my-server

# Filter events by type
python view_docker_db.py events --type manual_scale

# Limit results
python view_docker_db.py events --limit 10

# Filter scaling history by app
python view_docker_db.py scaling --app my-server

# Use different volume name
python view_docker_db.py summary --volume your_volume_name

# Get help
python view_docker_db.py --help


sqlite3 data/autoscaler.db "DELETE FROM scaling_history; DELETE FROM events; DELETE FROM instances; DELETE FROM apps; VACUUM;"

(1)TODO: if name of the container is conflicting, ask to delete(manually) and run again

(2)TODO: add 'docter' command for dependency check

(3)TODO: check if the image exists locally/remotely before registering

(4)TODO: auto heal dead containers without loosing any req/res
