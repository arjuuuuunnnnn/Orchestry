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

## Restart & Recovery Behavior

When the controller restarts, previously registered applications remain in the SQLite database (`apps` table). The controller now performs a reconciliation phase on startup:

1. Scans Docker for containers labeled with `autoserve.app=<name>`.
2. Adopts (starts if necessary) those containers instead of deleting them.
3. Ensures at least `minReplicas` are running (launches new ones only if needed).
4. Updates nginx upstream configuration with adopted instances.

You can verify after a restart:

```bash
python -m cli.main status my-server      # Should show existing replicas without re-register
python -m cli.main up my-server          # Idempotent; will adopt + top up to minReplicas
```

If containers were removed externally, `up` will recreate them. The start command response now includes fields:

```json
{"status":"started","app":"my-server","replicas":3,"adopted":2,"started":1}
```

Meaning: 2 existing containers adopted, 1 newly created, total 3.

## Troubleshooting After Restart

- If `status` shows replicas but `docker ps` does not: check logs for container creation failures.
- Name conflicts (Exited containers with same name) are resolved by adoption logic (container is started rather than recreated). Remove stale containers manually if corrupt:
	```bash
	docker rm -f my-server-0 my-server-1
	python -m cli.main up my-server
	```
- Network missing: controller recreates `autoserve` bridge automatically.
- If nginx upstreams not updating, inspect logs and ensure `autoserve-nginx` container is running.

## Database Persistence

AutoServe stores all app specifications in SQLite database (`data/autoscaler.db`). This ensures:

- **Restart Recovery**: After system restart, just run `python -m cli.main up my-server` - no need to re-register
- **Spec Preservation**: Original user specifications are stored exactly as submitted
- **Field Mapping**: `metadata.labels` are merged into `spec.labels`, `healthCheck` becomes `health`

### Retrieving Stored Specs

```bash
# Get normalized spec (how AutoServe processes it)
python -m cli.main spec my-server

# Get original submitted spec (raw YAML/JSON)  
python -m cli.main spec my-server --raw

# Via API
curl http://localhost:8000/apps/my-server/raw
```

The database persists:
- All user specifications (normalized + raw)
- Container instances and health status  
- Scaling events and decisions
- System events for audit



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
