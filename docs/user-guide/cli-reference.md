# CLI Reference

Complete reference for the AutoServe command-line interface.

## Installation

The CLI is automatically installed when you install AutoServe:

```bash
pip install autoserve
```

Or install from source

```bash
pip install -e .
```

## Global Options

```bash
autoserve [GLOBAL_OPTIONS] COMMAND [COMMAND_OPTIONS]
```

### Environment Variables

Configure the CLI with environment variables:

```bash
export AUTOSERVE_HOST=localhost      # Controller host
export AUTOSERVE_PORT=8000          # Controller port
export AUTOSERVE_TIMEOUT=30         # Request timeout (seconds)
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
autoserve config
```

This command:
- Prompts you for Host and Port
- Verifies the controller is reachable at http://HOST:PORT/health
- Saves the configuration to your OS config directory

On Linux the file is typically saved to:
- ~/.config/autoserve/config.yaml

On macOS:
- ~/Library/Application Support/autoserve/config.yaml

On Windows:
- %AppData%\autoserve\config.yaml

Saved file format:

```yaml
host: localhost
port: 8000
```

Examples:
```bash
# Run interactive setup
autoserve config
```

### register

Register an application from a specification file.

```bash
autoserve register [OPTIONS] CONFIG_FILE
```

**Arguments:**
- `CONFIG_FILE`: Path to YAML or JSON application specification

**Options:**
- `--validate-only`: Only validate the specification without registering

**Examples:**
```bash
# Register from YAML file
autoserve register my-app.yml

# Register from JSON file  
autoserve register my-app.json

# Validate specification only
autoserve register --validate-only my-app.yml
```

### up

Start a registered application.

```bash
autoserve up [OPTIONS] APP_NAME
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
autoserve up my-app

# Start with specific replica count
autoserve up my-app --replicas 3

# Start and wait for readiness
autoserve up my-app --wait --timeout 120
```

### down

Stop a running application.

```bash
autoserve down [OPTIONS] APP_NAME
```

**Arguments:**
- `APP_NAME`: Name of the application to stop

**Options:**
- `--force`: Force stop without graceful shutdown
- `--timeout INTEGER`: Graceful shutdown timeout (default: 30s)

**Examples:**
```bash
# Graceful stop
autoserve down my-app

# Force stop
autoserve down my-app --force

# Stop with custom timeout
autoserve down my-app --timeout 60
```

### scale

Scale an application to a specific number of replicas.

```bash
autoserve scale [OPTIONS] APP_NAME REPLICAS
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
autoserve scale my-app 5

# Scale and wait for completion
autoserve scale my-app 3 --wait

# Scale with custom timeout
autoserve scale my-app 2 --wait --timeout 180
```

## Information Commands

### status

Show application status and health.

```bash
autoserve status [OPTIONS] [APP_NAME]
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
autoserve status my-app

# Show all applications
autoserve status

# Watch status updates
autoserve status my-app --watch

# JSON output
autoserve status my-app --format json
```

### list

List all registered applications.

```bash
autoserve list [OPTIONS]
```

**Options:**
- `--format TEXT`: Output format (`table`, `json`, `yaml`)
- `--filter TEXT`: Filter by status (`running`, `stopped`, `error`)
- `--sort TEXT`: Sort by field (`name`, `status`, `replicas`, `created`)

**Examples:**
```bash
# List all applications
autoserve list

# List only running applications
autoserve list --filter running

# JSON output
autoserve list --format json

# Sort by creation time
autoserve list --sort created
```

### describe

Show detailed information about an application.

```bash
autoserve describe [OPTIONS] APP_NAME
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
autoserve describe my-app

# Include specification
autoserve describe my-app --show-spec

# JSON output with events
autoserve describe my-app --format json --show-events
```

## Monitoring Commands

### logs

View application container logs.

```bash
autoserve logs [OPTIONS] APP_NAME
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
autoserve logs my-app

# Follow logs
autoserve logs my-app --follow

# Show last 50 lines
autoserve logs my-app --tail 50

# Show logs from last hour
autoserve logs my-app --since 1h

# Show logs from specific container
autoserve logs my-app --container my-app-1
```

### events

Show application events and scaling decisions.

```bash
autoserve events [OPTIONS] APP_NAME
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
autoserve events my-app

# Follow events
autoserve events my-app --follow

# Show scaling events only
autoserve events my-app --type scaling

# Show events from last 2 hours
autoserve events my-app --since 2h
```

### metrics

Display application performance metrics.

```bash
autoserve metrics [OPTIONS] APP_NAME
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
autoserve metrics my-app

# Watch metrics updates
autoserve metrics my-app --watch

# JSON output with history
autoserve metrics my-app --format json --history 20
```

## Management Commands

### remove

Remove an application and all its resources.

```bash
autoserve remove [OPTIONS] APP_NAME
```

**Arguments:**
- `APP_NAME`: Name of the application to remove

**Options:**
- `--force`: Skip confirmation prompt
- `--keep-data`: Keep persistent data volumes

**Examples:**
```bash
# Remove application (with confirmation)
autoserve remove my-app

# Force remove without confirmation
autoserve remove my-app --force

# Remove but keep data volumes
autoserve remove my-app --keep-data
```

## Cluster Commands

### cluster status

Show cluster node status and leader information.

```bash
autoserve cluster status [OPTIONS]
```

**Options:**
- `--format TEXT`: Output format (`table`, `json`)
- `--watch`: Continuously update status

**Examples:**
```bash
# Show cluster status
autoserve cluster status

# Watch cluster changes
autoserve cluster status --watch

# JSON output
autoserve cluster status --format json
```

### cluster nodes

List all cluster nodes.

```bash
autoserve cluster nodes [OPTIONS]
```

**Options:**
- `--format TEXT`: Output format (`table`, `json`)

### cluster leader

Show current cluster leader information.

```bash
autoserve cluster leader [OPTIONS]
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
$ autoserve status my-app
❌ AutoServe controller is not running.

💡 To start AutoServe:
   docker-compose up -d

   Or use the quick start script:
   ./start.sh

# Application not found
$ autoserve status nonexistent
❌ Application 'nonexistent' not found.

💡 List available applications:
   autoserve list

# Invalid specification
$ autoserve register invalid.yml
❌ Validation failed: 
   - spec.image: Field required
   - scaling.minReplicas: Must be >= 1
```

## Configuration Files

### CLI Configuration

Create `~/.autoserve/config.yaml`:

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
AUTOSERVE_HOST=localhost
AUTOSERVE_PORT=8000
AUTOSERVE_TIMEOUT=30

# Authentication (future)
AUTOSERVE_TOKEN=your-api-token
```

## Bash Completion

Enable bash completion for the CLI:

```bash
# Add to ~/.bashrc or ~/.zshrc
eval "$(_AUTOSERVE_COMPLETE=bash_source autoserve)"

# Or generate completion script
_AUTOSERVE_COMPLETE=bash_source autoserve > ~/.autoserve-complete.bash
source ~/.autoserve-complete.bash
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