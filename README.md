# AutoServe

### Local Development
1. Copy `.env.example` to `.env`
2. Configure the values in `.env` for your local environment

### Docker Usage
1. Copy `.env.docker.example` to `.env.docker`  
2. Configure the values in `.env.docker` for Docker container paths
3. Run with `docker-compose up`

### Required Environment Variables
- `AUTOSERVE_HOST` - Host to bind controller to
- `AUTOSERVE_PORT` - Port for controller to listen on
- `AUTOSERVE_DB_PATH` - Path to SQLite database file
- `AUTOSERVE_NGINX_CONTAINER` - Name of nginx container
- `AUTOSERVE_NGINX_CONF_DIR` - Path to nginx configuration directory
- `API_URL` - API endpoint URL for CLI

**Important**: If any required environment variable is missing, the application will exit with an error message.

## API Endpoints

POST /api/v1/apps/register - Register applications

POST /api/v1/apps/{app_name}/start - Start apps

POST /api/v1/apps/{app_name}/stop - Stop apps

POST /api/v1/apps/{app_name}/scale - Scale apps

GET /api/v1/apps/{app_name} - Get app status

GET /api/v1/apps - List all apps

GET /health

## Usage

Python version == 3.13.5

python -m cli.main register my-server.yml
python -m cli.main up my-server
python -m cli.main down my-server
python -m cli.main status my-server
python -m cli.main scale my-server 3
python -m cli.main list
python -m cli.main metrics


### Retrieving Stored Specs

```bash
# Get normalized spec (how AutoServe processes it)
python -m cli.main spec my-server

# Get original submitted spec (raw YAML/JSON)  
python -m cli.main spec my-server --raw

# Via API
curl http://localhost:8000/apps/my-server/raw
```


python view_docker_db.py apps

python view_docker_db.py summary

python view_docker_db.py instances

python view_docker_db.py events

python view_docker_db.py scaling

python view_docker_db.py events --app my-server

python view_docker_db.py events --type manual_scale

python view_docker_db.py events --limit 10

python view_docker_db.py scaling --app my-server

python view_docker_db.py summary --volume your_volume_name

python view_docker_db.py --help


sqlite3 data/autoscaler.db "DELETE FROM scaling_history; DELETE FROM events; DELETE FROM instances; DELETE FROM apps; VACUUM;"

(1)TODO: if name of the container is conflicting, ask to delete(manually) and run again

(2)TODO: add 'docter' command for dependency check

(3)TODO: check if the image exists locally/remotely before registering

(4)TODO: auto heal dead containers without loosing any req/res (auto healing is done, handling reqests of dead servers needs to be taken care)
