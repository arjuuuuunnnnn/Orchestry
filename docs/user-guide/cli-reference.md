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

## Global Options

```bash
orchestry [GLOBAL_OPTIONS] COMMAND [COMMAND_OPTIONS]
```

### Environment Variables

Configure the CLI with environment variables:

```bash
export ORCHESTRY_HOST=localhost      # Controller host
export ORCHETSRY_PORT=8000          # Controller port
export ORCHESTRY_TIMEOUT=30         # Request timeout (seconds)
```

## Commands Overview

| Command | Description |
|---------|-------------|
| `config` | Configure the controller endpoint (interactive) |
| `register` | Register an application from YAML/JSON spec |
| `up` | Start an application |
| `down` | Stop an application |
| `scale` | Scale an application to specific replica count |
| `status` | Show application status |
| `list` | List all applications |
| `describe` | Show detailed application information |
| `logs` | View application logs |
| `events` | Show application events |
| `metrics` | Display application metrics |
| `remove` | Remove an application |
| `cluster` | Cluster management commands |

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

On Linux the file is typically saved to:
- ~/.config/orchestry/config.yaml

On macOS:
- ~/Library/Application Support/orchestry/config.yaml

On Windows:
- %AppData%\orchestry\config.yaml

Saved file format:

```yaml
host: localhost
port: 8000
```

Examples:
```bash
# Run interactive setup
orchestry config
```

### register

Register an application from a specification file.

```bash
orchestry register [OPTIONS] CONFIG_FILE
```

**Arguments:**
- `CONFIG_FILE`: Path to YAML or JSON application specification

**Options:**
- `--validate-only`: Only validate the specification without registering

**Examples:**
```bash
# Register from YAML file
orchestry register my-app.yml

# Register from JSON file  
orchestry register my-app.json

# Validate specification only
orchestry register --validate-only my-app.yml
```

### up

Start a registered application.

```bash
orchestry up [OPTIONS] APP_NAME
```

**Arguments:**
- `APP_NAME`: Name of the application to start

**Options:**
- `--replicas INTEGER`: Initial number of replicas (overrides spec)
- `--wait`: Wait for application to be ready
- `--timeout INTEGER`: Timeout for waiting (default: 300s)

**Examples:**
```bash
# Start application
orchestry up my-app

# Start with specific replica count
orchestry up my-app --replicas 3

# Start and wait for readiness
orchestry up my-app --wait --timeout 120
```

### down

Stop a running application.

```bash
orchestry down [OPTIONS] APP_NAME
```

**Arguments:**
- `APP_NAME`: Name of the application to stop

**Options:**
- `--force`: Force stop without graceful shutdown
- `--timeout INTEGER`: Graceful shutdown timeout (default: 30s)

**Examples:**
```bash
# Graceful stop
orchestry down my-app

# Force stop
orchestry down my-app --force

# Stop with custom timeout
orchestry down my-app --timeout 60
```

### scale

Scale an application to a specific number of replicas.

```bash
orchestry scale [OPTIONS] APP_NAME REPLICAS
```

**Arguments:**
- `APP_NAME`: Name of the application to scale
- `REPLICAS`: Target number of replicas

**Options:**
- `--wait`: Wait for scaling to complete
- `--timeout INTEGER`: Timeout for waiting (default: 300s)

**Examples:**
```bash
# Scale to 5 replicas
orchestry scale my-app 5

# Scale and wait for completion
orchestry scale my-app 3 --wait

# Scale with custom timeout
orchestry scale my-app 2 --wait --timeout 180
```

## Information Commands

### status

Show application status and health.

```bash
orchestry status [OPTIONS] [APP_NAME]
```

**Arguments:**
- `APP_NAME`: Application name (optional, shows all if omitted)

**Options:**
- `--format TEXT`: Output format (`table`, `json`, `yaml`)
- `--watch`: Continuously update status
- `--interval INTEGER`: Update interval for watch mode (default: 5s)

**Examples:**
```bash
# Show status of specific app
orchestry status my-app

# Show all applications
orchestry status

# Watch status updates
orchestry status my-app --watch

# JSON output
orchestry status my-app --format json
```

### list

List all registered applications.

```bash
orchestry list [OPTIONS]
```

**Options:**
- `--format TEXT`: Output format (`table`, `json`, `yaml`)
- `--filter TEXT`: Filter by status (`running`, `stopped`, `error`)
- `--sort TEXT`: Sort by field (`name`, `status`, `replicas`, `created`)

**Examples:**
```bash
# List all applications
orchestry list

# List only running applications
orchestry list --filter running

# JSON output
orchestry list --format json

# Sort by creation time
orchestry list --sort created
```

### describe

Show detailed information about an application.

```bash
orchestry describe [OPTIONS] APP_NAME
```

**Arguments:**
- `APP_NAME`: Name of the application

**Options:**
- `--format TEXT`: Output format (`yaml`, `json`)
- `--show-spec`: Include original specification
- `--show-events`: Include recent events

**Examples:**
```bash
# Describe application
orchestry describe my-app

# Include specification
orchestry describe my-app --show-spec

# JSON output with events
orchestry describe my-app --format json --show-events
```

## Monitoring Commands

### logs

View application container logs.

```bash
orchestry logs [OPTIONS] APP_NAME
```

**Arguments:**
- `APP_NAME`: Name of the application

**Options:**
- `--follow, -f`: Follow log output
- `--tail INTEGER`: Number of lines to show from end (default: 100)
- `--since TEXT`: Show logs since timestamp or duration (`1h`, `30m`, `2024-01-01T10:00:00`)
- `--container TEXT`: Show logs from specific container

**Examples:**
```bash
# Show recent logs
orchestry logs my-app

# Follow logs
orchestry logs my-app --follow

# Show last 50 lines
orchestry logs my-app --tail 50

# Show logs from last hour
orchestry logs my-app --since 1h

# Show logs from specific container
orchestry logs my-app --container my-app-1
```

### events

Show application events and scaling decisions.

```bash
orchestry events [OPTIONS] APP_NAME
```

**Arguments:**
- `APP_NAME`: Name of the application

**Options:**
- `--follow, -f`: Follow events
- `--since TEXT`: Show events since timestamp or duration
- `--type TEXT`: Filter by event type (`scaling`, `health`, `config`, `error`)

**Examples:**
```bash
# Show recent events
orchestry events my-app

# Follow events
orchestry events my-app --follow

# Show scaling events only
orchestry events my-app --type scaling

# Show events from last 2 hours
orchestry events my-app --since 2h
```

### metrics

Display application performance metrics.

```bash
orchestry metrics [OPTIONS] APP_NAME
```

**Arguments:**
- `APP_NAME`: Name of the application

**Options:**
- `--watch`: Continuously update metrics
- `--interval INTEGER`: Update interval (default: 10s)
- `--format TEXT`: Output format (`table`, `json`)
- `--history INTEGER`: Show historical data points (default: 10)

**Examples:**
```bash
# Show current metrics
orchestry metrics my-app

# Watch metrics updates
orchestry metrics my-app --watch

# JSON output with history
orchestry metrics my-app --format json --history 20
```

## Management Commands

### remove

Remove an application and all its resources.

```bash
orchestry remove [OPTIONS] APP_NAME
```

**Arguments:**
- `APP_NAME`: Name of the application to remove

**Options:**
- `--force`: Skip confirmation prompt
- `--keep-data`: Keep persistent data volumes

**Examples:**
```bash
# Remove application (with confirmation)
orchestry remove my-app

# Force remove without confirmation
orchestry remove my-app --force

# Remove but keep data volumes
orchestry remove my-app --keep-data
```

## Cluster Commands

### cluster status

Show cluster node status and leader information.

```bash
orchestry cluster status [OPTIONS]
```

**Options:**
- `--format TEXT`: Output format (`table`, `json`)
- `--watch`: Continuously update status

**Examples:**
```bash
# Show cluster status
orchestry cluster status

# Watch cluster changes
orchestry cluster status --watch

# JSON output
orchestry cluster status --format json
```

### cluster nodes

List all cluster nodes.

```bash
orchestry cluster nodes [OPTIONS]
```

**Options:**
- `--format TEXT`: Output format (`table`, `json`)

### cluster leader

Show current cluster leader information.

```bash
orchestry cluster leader [OPTIONS]
```

## Output Formats

### Table Format (Default)

Human-readable tabular output:

```
NAME       STATUS    REPLICAS  CPU%   MEMORY%  RPS    LATENCY
my-app     running   3/3       45.2   62.1     127    89ms
web-api    running   2/5       78.9   71.3     203    156ms
```

### JSON Format

Machine-readable JSON output:

```json
{
  "apps": [
    {
      "name": "my-app",
      "status": "running",
      "replicas": {
        "current": 3,
        "desired": 3
      },
      "metrics": {
        "cpu_percent": 45.2,
        "memory_percent": 62.1,
        "rps": 127,
        "latency_p95_ms": 89
      }
    }
  ]
}
```

### YAML Format

YAML output for configuration files:

```yaml
apps:
  - name: my-app
    status: running
    replicas:
      current: 3
      desired: 3
    metrics:
      cpu_percent: 45.2
      memory_percent: 62.1
      rps: 127
      latency_p95_ms: 89
```

## Error Handling

The CLI provides helpful error messages and suggestions:

```bash
# Service not running
$ orchestry status my-app
❌ Orchestry controller is not running.

💡 To start Orchestry:
   docker-compose up -d

   Or use the quick start script:
   ./start.sh

# Application not found
$ orchestry status nonexistent
❌ Application 'nonexistent' not found.

💡 List available applications:
   orchestry list

# Invalid specification
$ orchestry register invalid.yml
❌ Validation failed: 
   - spec.image: Field required
   - scaling.minReplicas: Must be >= 1
```

## Configuration Files

### CLI Configuration

Create `~/.orchestry/config.yaml`:

```yaml
# Default controller endpoint
controller:
  host: localhost
  port: 8000
  timeout: 30

# Default output preferences
output:
  format: table
  colors: true

# Default scaling options
scaling:
  wait_timeout: 300
  check_interval: 5
```

### Environment Configuration

Create `.env` file in your working directory:

```bash
# Controller settings
ORCHESTRY_HOST=localhost
ORCHESTRY_PORT=8000
ORCHESTRY_TIMEOUT=30

# Authentication (future)
ORCHESTRY_TOKEN=your-api-token
```

## Bash Completion

Enable bash completion for the CLI:

```bash
# Add to ~/.bashrc or ~/.zshrc
eval "$(_ORCHESTRY_COMPLETE=bash_source orchestry)"

# Or generate completion script
_ORCHESTRY_COMPLETE=bash_source orchestry > ~/.orchestry-complete.bash
source ~/.orchestry-complete.bash
```

## Tips and Best Practices

1. **Use descriptive app names**: Choose DNS-compatible names
2. **Monitor before scaling**: Check metrics before manual scaling
3. **Use --wait for critical operations**: Ensure operations complete
4. **Follow logs during deployment**: Use `--follow` to monitor startup
5. **Regular health checks**: Monitor application events
6. **Backup specifications**: Keep your YAML files in version control

---

**Next Steps**: Learn about [Application Specifications](app-spec.md) to define your applications.