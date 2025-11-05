# CLI Reference

Complete reference for the Orchestry command-line interface.

## Installation

The CLI is automatically installed when you install Orchestry:

```bash
pip install orchestry
```

Or install from source

```bash
pip install -e .
```

## Options

```bash
orchestry --help
```

## Commands Overview

| Command | Description |
|---------|-------------|
| `config` | Configure the controller endpoint (interactive) |
| `register` | Register an application from YAML/JSON spec |
| `up` | Start an application |
| `down` | Stop an application |
| `delete` | Delete an application completely (stops & removes) |
| `status` | Show application status |
| `scale` | Scale an application to specific replica count |
| `list` | List all applications |
| `metrics` | Get system or app metrics |
| `info` | Show orchestry system information and status |
| `spec` | Get app specification (supports --raw flag) |
| `logs` | View application logs |
| `cluster` | Get cluster information (status, leader, health) |
| `events` | Get recent events |

## Application Management

### config

Interactively configure the controller endpoint used by all commands.

```bash
orchestry config
```

This command:
- Prompts you for Host and Port
- Verifies the controller is reachable at http://HOST:PORT/health
- Saves the configuration to your OS config directory

**Examples:**
```bash
# Run interactive setup
orchestry config
```

### register

Register an application from a specification file.

```bash
orchestry register CONFIG_FILE
```

**Arguments:**
- `CONFIG_FILE`: Path to YAML or JSON application specification

**Examples:**
```bash
# Register from YAML file
orchestry register my-app.yml

# Register from JSON file  
orchestry register my-app.json
```

### up

Start a registered application.

```bash
orchestry up APP_NAME
```

**Arguments:**
- `APP_NAME`: Name of the application to start

**Examples:**
```bash
# Start application
orchestry up my-app
```

### down

Stop a running application.

```bash
orchestry down APP_NAME
```

**Arguments:**
- `APP_NAME`: Name of the application to stop

**Examples:**
```bash
# Stop application
orchestry down my-app
```

### delete

Delete an application completely (stops containers and removes registration).

```bash
orchestry delete APP_NAME [--force]
```

**Arguments:**
- `APP_NAME`: Name of the application to delete

**Options:**
- `--force, -f`: Skip confirmation prompt

**Examples:**
```bash
# Delete application (with confirmation)
orchestry delete my-app

# Delete application (skip confirmation)
orchestry delete my-app --force
orchestry delete my-app -f
```

**What happens:**
- All running containers are stopped and removed
- Health checks are unregistered
- Nginx configuration is removed
- Application is removed from the database
- Deletion event is logged for audit trail

**Warning:** This action cannot be undone. You will need to re-register the application if you want to use it again.

### scale

Scale an application to a specific number of replicas.

```bash
orchestry scale APP_NAME REPLICAS
```

**Arguments:**
- `APP_NAME`: Name of the application to scale
- `REPLICAS`: Target number of replicas

**Examples:**
```bash
# Scale to 5 replicas
orchestry scale my-app 5

# Scale to 3 replicas
orchestry scale my-app 3
```

**Note:** If the app is in auto mode, autoscaling may override the manual scaling. To prevent this, set `mode: manual` in the scaling section of your YAML spec.

## Information Commands

### status

Show application status and health.

```bash
orchestry status APP_NAME
```

**Arguments:**
- `APP_NAME`: Application name

**Examples:**
```bash
# Show status of specific app
orchestry status my-app
```

### list

List all registered applications.

```bash
orchestry list
```

**Examples:**
```bash
# List all applications
orchestry list
```

### info

Show orchestry system information and status.

```bash
orchestry info
```

**Examples:**
```bash
# Show system info
orchestry info
```

This displays:
- Orchestry Controller status
- API endpoint
- Number of registered apps
- Docker services status

### spec

Get app specification.

```bash
orchestry spec APP_NAME [--raw]
```

**Arguments:**
- `APP_NAME`: Name of the application

**Options:**
- `--raw`: Show the original submitted spec (default: false)

**Examples:**
```bash
# Get parsed specification
orchestry spec my-app

# Get raw specification as originally submitted
orchestry spec my-app --raw
```

## Monitoring Commands

### logs

View application container logs.

```bash
orchestry logs APP_NAME [OPTIONS]
```

**Arguments:**
- `APP_NAME`: Name of the application

**Options:**
- `--lines, -n INTEGER`: Number of log lines to retrieve (default: 100)
- `--follow, -f`: Follow log output (not yet implemented)

**Examples:**
```bash
# Show recent logs (last 100 lines)
orchestry logs my-app

# Show last 50 lines
orchestry logs my-app --lines 50

# Show last 200 lines
orchestry logs my-app -n 200
```

**Note:** The `--follow` option is recognized but not yet implemented. Logs are displayed sorted by timestamp across all containers.

### events

Get recent events.

```bash
orchestry events
```

**Examples:**
```bash
# Show recent events
orchestry events
```

### metrics

Get system or app metrics.

```bash
orchestry metrics [APP_NAME]
```

**Arguments:**
- `APP_NAME`: Name of the application (optional)

**Examples:**
```bash
# Show system metrics
orchestry metrics

# Show metrics for specific app
orchestry metrics my-app
```

## Cluster Commands

### cluster

Get cluster information (status, leader, health).

```bash
orchestry cluster OPTS
```

**Arguments:**
- `OPTS`: Options like `status`, `leader`, or `health`

**Examples:**
```bash
# Show cluster status
orchestry cluster status

# Show cluster leader
orchestry cluster leader

# Show cluster health
orchestry cluster health
```

## Output Format

All commands return JSON-formatted output that can be piped to other tools like `jq` for parsing:

```bash
# Pretty-print with jq
orchestry list | jq .

# Get specific field
orchestry status my-app | jq '.status'
```

## Error Handling

The CLI provides clear error messages:

```bash
# Service not running
$ orchestry status my-app
 orchestry controller is not running, run 'orchestry config' to configure

# Application not found
$ orchestry status nonexistent
 App 'nonexistent' not found

# Registration failed
$ orchestry register invalid.yml
 Registration failed: {...}
```

## Tips and Best Practices

1. **Configure first**: Always run `orchestry config` before using other commands
2. **Use descriptive app names**: Choose clear, meaningful names for your applications
3. **Monitor scaling**: For apps in auto mode, remember that manual scaling may be overridden
4. **Keep specs in version control**: Store your YAML/JSON specs in git
5. **Check info regularly**: Use `orchestry info` to monitor system health

---

**Next Steps**: Learn about [Application Specifications](app-spec.md) to define your applications.