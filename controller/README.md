# AutoServe Controller

The AutoServe Controller is the core daemon that manages Docker container lifecycle, autoscaling, and load balancing for HTTP applications without Kubernetes.

## Features

- **Container Management**: Start, stop, and scale Docker containers automatically
- **Health Monitoring**: HTTP health checks with configurable thresholds
- **Autoscaling**: CPU, memory, and traffic-based scaling decisions
- **Load Balancing**: Automatic Nginx configuration management
- **State Management**: Persistent storage of app specs and scaling history
- **REST API**: Complete API for management and monitoring

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   CLI Client    │───▶│   Controller    │───▶│ Docker Engine   │
└─────────────────┘    │      API        │    └─────────────────┘
                       └─────────────────┘              │
                               │                        ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│     Nginx       │◀───│   State Store   │    │  App Containers │
│ Load Balancer   │    │   (SQLite)      │    └─────────────────┘
└─────────────────┘    └─────────────────┘
```

## Components

### AppManager (`manager.py`)
- Manages Docker container lifecycle using Docker API
- Handles scaling operations (scale up/down)
- Monitors container health and metrics
- Integrates with Nginx for load balancer updates

### StateStore (`state.py`)
- SQLite-based persistent storage
- Stores app specifications, instance records, events
- Tracks scaling history and audit logs
- Provides data consistency across restarts

### AutoScaler (`scaler.py`)
- Makes intelligent scaling decisions based on metrics
- Supports CPU, memory, RPS, and latency-based scaling
- Implements hysteresis to prevent scaling flapping
- Configurable policies per application

### NginxManager (`nginx.py`)
- Generates and updates Nginx configuration files
- Performs graceful reloads without downtime
- Manages upstream server pools automatically
- Provides load balancing and health checking

### HealthChecker (`health.py`)
- Performs HTTP health checks on containers
- Configurable intervals, timeouts, and thresholds
- Integrates with load balancer for traffic routing
- Provides health status reporting

### API (`api.py`)
- FastAPI-based REST interface
- Endpoints for registration, scaling, monitoring
- Background monitoring and scaling loops
- Prometheus-compatible metrics export

## Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Ensure Docker is running and accessible:
```bash
docker info
```

3. Ensure Nginx is installed (for HTTP load balancing):
```bash
nginx -v
```

## Usage

### Starting the Controller

Run the controller daemon:
```bash
python controller/main.py --host 0.0.0.0 --port 8000
```

Options:
- `--host`: Host to bind API server (default: 0.0.0.0)
- `--port`: Port for API server (default: 8000)
- `--log-level`: Logging level (DEBUG, INFO, WARNING, ERROR)
- `--db-path`: SQLite database path (default: autoscaler.db)
- `--nginx-conf-dir`: Nginx config directory (default: /etc/nginx/conf.d)

### Registering an Application

Create an app specification (YAML):
```yaml
apiVersion: v1
kind: App
metadata:
  name: my-app
spec:
  type: http
  image: my-app:latest
  ports:
    - containerPort: 8080
  scaling:
    minReplicas: 1
    maxReplicas: 10
    policy:
      http:
        targetRPSPerReplica: 50
        scaleOutThresholdPct: 80
```

Register via API:
```bash
curl -X POST http://localhost:8000/apps/register \
  -H "Content-Type: application/json" \
  -d @app-spec.json
```

### Managing Applications

Start an application:
```bash
curl -X POST http://localhost:8000/apps/my-app/up
```

Check status:
```bash
curl http://localhost:8000/apps/my-app/status
```

Scale manually:
```bash
curl -X POST http://localhost:8000/apps/my-app/scale \
  -H "Content-Type: application/json" \
  -d '{"replicas": 3}'
```

Stop an application:
```bash
curl -X POST http://localhost:8000/apps/my-app/down
```

### Monitoring

Get system metrics:
```bash
curl http://localhost:8000/metrics
```

Get application metrics:
```bash
curl http://localhost:8000/apps/my-app/metrics
```

View scaling history:
```bash
curl http://localhost:8000/apps/my-app/metrics
```

List all applications:
```bash
curl http://localhost:8000/apps
```

## Configuration

### Application Specification

Applications are defined using a declarative YAML/JSON specification:

```yaml
apiVersion: v1
kind: App
metadata:
  name: my-app
spec:
  type: http                    # Application type (only 'http' supported currently)
  image: my-app:latest         # Docker image
  command: ["/entrypoint"]     # Optional: override container command
  
  # Port configuration
  ports:
    - containerPort: 8080
  
  # Health check configuration
  health:
    httpGet:
      path: /healthz
      port: 8080
    intervalSeconds: 5
    timeoutSeconds: 2
    failureThreshold: 3
  
  # Resource limits
  resources:
    cpu: 0.5                   # CPU cores
    memory: 512Mi              # Memory limit
  
  # Scaling configuration
  scaling:
    minReplicas: 1
    maxReplicas: 10
    policy:
      mode: auto
      cooldownSeconds: 30
      http:
        targetRPSPerReplica: 50
        maxP95LatencyMs: 200
        scaleOutThresholdPct: 80
        scaleInThresholdPct: 30
        windowSeconds: 20
  
  # Environment variables
  env:
    - name: NODE_ENV
      value: production
    - name: REDIS_URL
      valueFrom: sdk           # SDK-provided values
  
  # Graceful shutdown
  termination:
    drainSeconds: 30
```

### Scaling Policies

The autoscaler supports multiple metrics for scaling decisions:

- **CPU utilization**: Scale based on average CPU usage
- **Memory utilization**: Scale based on average memory usage  
- **RPS (Requests Per Second)**: Scale based on traffic load
- **Response latency**: Scale based on application response times
- **Active connections**: Scale based on concurrent connections

Scaling decisions use hysteresis to prevent flapping:
- Scale out when metrics exceed `scaleOutThresholdPct` for `windowSeconds`
- Scale in when metrics are below `scaleInThresholdPct` for `windowSeconds`
- Enforce `cooldownSeconds` between scaling operations

## API Reference

### Core Endpoints

- `POST /apps/register` - Register a new application
- `POST /apps/{name}/up` - Start an application
- `POST /apps/{name}/down` - Stop an application
- `GET /apps/{name}/status` - Get application status
- `POST /apps/{name}/scale` - Manual scaling
- `GET /apps` - List all applications

### Monitoring Endpoints

- `GET /metrics` - System-wide metrics
- `GET /apps/{name}/metrics` - Application-specific metrics
- `GET /apps/{name}/logs` - Application logs
- `GET /events` - System events and audit log

### Policy Management

- `POST /apps/{name}/policy` - Update scaling policy

## Security Considerations

- The controller requires Docker socket access (`/var/run/docker.sock`)
- Nginx configuration requires appropriate file system permissions
- API server should be protected by firewall/network policies
- Container resource limits are enforced to prevent resource exhaustion

## Troubleshooting

### Common Issues

1. **Docker permission denied**: Ensure the user running the controller has Docker access
2. **Nginx reload fails**: Check Nginx configuration syntax and permissions
3. **Container fails to start**: Check image availability and resource limits
4. **Health checks failing**: Verify health check endpoint and network connectivity

### Logs

The controller logs to both stdout and `autoserve-controller.log`:
```bash
tail -f autoserve-controller.log
```

### Database

Inspect the SQLite database for debugging:
```bash
sqlite3 autoscaler.db ".tables"
sqlite3 autoscaler.db "SELECT * FROM apps;"
```

## Development

### Running Tests

```bash
python -m pytest tests/
```

### Contributing

1. Follow PEP 8 style guidelines
2. Add tests for new functionality
3. Update documentation for API changes
4. Ensure backward compatibility

## Limitations

- Currently supports only HTTP workloads (Worker mode planned)
- Single-host deployment (multi-host clustering planned)
- Nginx-only load balancing (Traefik/Envoy planned)
- Basic metric collection (enhanced monitoring planned)

## Roadmap

- Worker mode for background job processing
- Multi-host clustering with leader election
- Enhanced metrics collection and dashboards
- Integration with external monitoring systems
- UI dashboard for management and monitoring
