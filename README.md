# AutoServe

**AutoServe** is a lightweight container orchestration and auto-scaling platform designed for web applications. It provides intelligent load balancing, automated scaling, health monitoring, and seamless deployment management through Docker containers and Nginx proxy configuration.

## Features

### Core Capabilities
- **Container Orchestration**: Deploy and manage Docker containers with YAML/JSON specifications
- **Auto-Scaling**: Intelligent scaling based on CPU, memory, RPS, latency, and connection metrics
- **Load Balancing**: Dynamic Nginx configuration with upstream management
- **Health Monitoring**: Continuous health checks with automatic recovery
- **CLI Management**: Powerful command-line interface for app lifecycle management
- **RESTful API**: Complete REST API for programmatic control
- **Persistent State**: SQLite-based state management with audit trails

### Advanced Features
- **Scaling Policies**: Configurable scaling rules and thresholds
- **Metrics Collection**: Real-time performance and resource monitoring
- **Event Logging**: Comprehensive audit trail for all operations
- **Multi-Mode Scaling**: Support for both automatic and manual scaling modes
- **Resource Constraints**: CPU and memory limit enforcement
- **Service Discovery**: Automatic container registration and deregistration

## Architecture

AutoServe follows a microservices architecture with the following components:

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   CLI Client    │    │   REST API      │    │  Nginx Proxy    │
│                 │    │   (FastAPI)     │    │                 │
└─────────┬───────┘    └─────────┬───────┘    └─────────┬───────┘
          │                      │                      │
          └──────────────────────┼──────────────────────┘
                                 │
                   ┌─────────────┴───────────┐
                   │   AutoServe Controller  │
                   │                         │
                   │  • App Manager          │
                   │  • Auto Scaler          │
                   │  • Health Checker       │
                   │  • Nginx Manager        │
                   │  • State Manager        │
                   └─────────────┬───────────┘
                                 │
                   ┌─────────────┴───────────┐
                   │     Docker Engine       │
                   │                         │
                   │  [App1] [App2] [App3]   │
                   └─────────────────────────┘
```

## Prerequisites

- **Docker** and **Docker Compose**
- **Python 3.13+**
- **Linux/macOS** (recommended)

## Installation

### 1. Clone the Repository
```bash
git clone https://github.com/arjuuuuunnnnn/AutoServe.git
cd AutoServe
```

### 2. Environment Setup
Create a `.env.docker` file:
```bash
cp .env.docker.example .env.docker
```

Configure your environment variables:
```env
AUTOSERVE_HOST=0.0.0.0
AUTOSERVE_PORT=8000
AUTOSERVE_DB_PATH=./data/autoscaler.db
AUTOSERVE_NGINX_CONTAINER=autoserve-nginx
```

Create `.env.docker` for container environment:
```env
AUTOSERVE_PORT=8000
AUTOSERVE_DB_PATH=/app/data/autoscaler.db
AUTOSERVE_NGINX_CONTAINER=autoserve-nginx
```

### 3. Deploy with Docker Compose
```bash
docker-compose up --build -d
```

This will start:
- AutoServe Controller (port 8000)
- Nginx Load Balancer (ports 80, 443)

### 4. Install CLI (Optional)
```bash
pip install -r requirements.txt
```

## Quick Start

### Register an Application

Create an application specification file (`my-server.yml`):
```yaml
apiVersion: v1
kind: App
metadata:
  name: my-server
  labels:
    app: "my-server" #must be dns compatible
    version: "v1"
spec:
  type: http
  image: "testing:latest" #server's docker image
  ports:
    - containerPort: 9010
      protocol: HTTP
  resources:
    cpu: "100m"
    memory: "128Mi"
scaling:
  mode: auto # or manual
  minReplicas: 1
  maxReplicas: 5
  targetRPSPerReplica: 100
  maxP95LatencyMs: 500
  scaleOutThresholdPct: 80
  scaleInThresholdPct: 60
healthCheck:
  path: "/"
  port: 9010
  initialDelaySeconds: 5
  periodSeconds: 10
```

### Deploy the Application

**Using CLI:**
```bash
# Register the app
python -m cli.main register my-server.yml

# Start the app
python -m cli.main up my-server

# Check status
python -m cli.main status my-server

# Scale manually
python -m cli.main scale my-server 3

# Stop the app
python -m cli.main down my-server
```

**Using REST API:**
```bash
# Register app
curl -X POST http://localhost:8000/apps/register \
  -H "Content-Type: application/json" \
  -d @my-app.json

# Start app
curl -X POST http://localhost:8000/apps/my-web-app/up

# Check status
curl http://localhost:8000/apps/my-web-app/status

# Scale app
curl -X POST http://localhost:8000/apps/my-web-app/scale \
  -H "Content-Type: application/json" \
  -d '{"replicas": 3}'
```


## REST API Reference

### Core Endpoints

#### Application Management
- `POST /apps/register` - Register new application
- `GET /apps` - List all applications
- `GET /apps/{name}` - Get application details
- `POST /apps/{name}/up` - Start application
- `POST /apps/{name}/down` - Stop application
- `DELETE /apps/{name}` - Remove application

#### Scaling & Monitoring
- `GET /apps/{name}/status` - Get application status
- `POST /apps/{name}/scale` - Scale application
- `GET /apps/{name}/metrics` - Get application metrics
- `GET /apps/{name}/events` - Get application events

#### System Management
- `GET /health` - System health check
- `GET /metrics` - System metrics
- `POST /policies/{name}` - Update scaling policy

### Example API Usage

```python
import requests

# Register application
spec = {
    "apiVersion": "v1",
    "kind": "App",
    "metadata": {"name": "my-app"},
    "spec": {
        "type": "http",
        "image": "nginx:alpine",
        "ports": [{"containerPort": 80, "protocol": "HTTP"}]
    }
}

response = requests.post("http://localhost:8000/apps/register", json=spec)
print(response.json())
```

## Configuration

### Application Specification Schema

```yaml
apiVersion: v1                    # API version
kind: App                         # Resource type

metadata:
  name: string                    # Application name (required)
  labels:                         # Key-value labels
    app: string
    version: string

spec:
  type: http|tcp                  # Application type
  image: string                   # Docker image (required)
  ports:                          # Port configuration
    - containerPort: int          # Container port
      protocol: HTTP|TCP          # Protocol type
  
  resources:                      # Resource constraints
    cpu: string                   # CPU limit (e.g., "100m", "1")
    memory: string                # Memory limit (e.g., "128Mi", "1Gi")
  
  env:                           # Environment variables
    - name: string
      value: string
      source: value|sdk|secret    # Variable source

  command: [string]              # Override container command
  args: [string]                 # Container arguments

scaling:                         # Scaling configuration
  mode: auto|manual              # Scaling mode
  minReplicas: int               # Minimum replicas
  maxReplicas: int               # Maximum replicas
  targetCPU: int                 # Target CPU percentage
  targetMemory: int              # Target memory percentage
  targetRPS: int                 # Target requests per second
  targetLatency: int             # Target latency (ms)
  scaleUpCooldown: int           # Scale up cooldown (seconds)
  scaleDownCooldown: int         # Scale down cooldown (seconds)

healthCheck:                     # Health check configuration
  path: string                   # Health check path
  port: int                      # Health check port
  initialDelaySeconds: int       # Initial delay
  periodSeconds: int             # Check interval
  timeoutSeconds: int            # Request timeout
  failureThreshold: int          # Failure threshold
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `AUTOSERVE_HOST` | Controller host | `127.0.0.1` |
| `AUTOSERVE_PORT` | Controller port | `8000` |
| `AUTOSERVE_DB_PATH` | Database file path | `./data/autoscaler.db` |
| `AUTOSERVE_NGINX_CONTAINER` | Nginx container name | `autoserve-nginx` |
| `DOCKER_HOST` | Docker daemon socket | `unix:///var/run/docker.sock` |

## Monitoring & Metrics

### Available Metrics
- **Application Metrics**: CPU usage, memory usage, request rate, response time
- **Container Metrics**: Health status, restart count, uptime
- **System Metrics**: Total applications, total containers, resource utilization
- **Scaling Metrics**: Scaling events, policy triggers, cooldown status

### Health Monitoring
AutoServe continuously monitors application health through:
- HTTP health check endpoints
- Container status monitoring
- Resource usage tracking
- Response time measurement

## Development

### Project Structure
```
AutoServe/
├── app_spec/              # Application specification models
├── cli/                   # Command-line interface
├── controller/            # Core controller logic
│   ├── api.py            # REST API endpoints
│   ├── manager.py        # Application manager
│   ├── scaler.py         # Auto-scaling engine
│   ├── health.py         # Health monitoring
│   ├── nginx.py          # Nginx configuration
│   └── state.py          # State management
├── docker_configs/        # Docker and Nginx configurations
├── metrics/              # Metrics collection
├── state/                # Database and persistence
├── test/                 # Test configurations
└── logs/                 # Application logs
```

### Running in Development Mode

```bash
# Install dependencies
pip install -r requirements.txt

# Set up environment
export AUTOSERVE_HOST=localhost
export AUTOSERVE_PORT=8000

# Run controller
python controller/main.py --log-level DEBUG

# Run CLI commands
python -m cli.main --help
```

### Testing

```bash
# Run load tests
cd test/
./load_test.sh

# Test with sample applications
python -m cli.main register test/my-server.yml
python -m cli.main up my-server
```

## 🐛 Troubleshooting

### Common Issues

**1. Container fails to start**
```bash
# Check application logs
python -m cli.main logs <app-name>

# Check system events
curl http://localhost:8000/apps/<app-name>/events
```

**2. Auto-scaling not working**
```bash
# Verify scaling policy
curl http://localhost:8000/apps/<app-name>/status

# Check metrics collection
curl http://localhost:8000/apps/<app-name>/metrics
```

**3. Nginx configuration issues**
```bash
# Check Nginx container logs
docker logs autoserve-nginx

# Verify upstream configuration
docker exec autoserve-nginx cat /etc/nginx/conf.d/default.conf
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Support

- **GitHub Issues**: [Report bugs or request features](https://github.com/arjuuuuunnnnn/AutoServe/issues)
- **Examples**: Check the [test](./test) directory for configuration examples

## 🔮 Roadmap

- [ ] **Secret Management**: Integrated secret storage and injection
- [ ] **Service Mesh**: Advanced networking and security features
- [ ] **Multi-Host Support**: Distributed container orchestration
- [ ] **Advanced Metrics**: Prometheus integration and custom dashboards
- [ ] **Blue-Green Deployments**: Zero-downtime deployment strategies
- [ ] **WebSocket Support**: Real-time application support
- [ ] **Database Integration**: Managed database services
- [ ] **CI/CD Integration**: GitHub Actions and GitLab CI support

---

**AutoServe** - Simplifying container orchestration and auto-scaling for modern web applications.
