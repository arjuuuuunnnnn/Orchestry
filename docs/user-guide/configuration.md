# Configuration Guide

Complete guide to configuring Orchestry for different environments and use cases.

## Configuration Overview

Orchestry can be configured through multiple methods:

1. **Environment Variables** - Runtime configuration
2. **Configuration Files** - Structured configuration
3. **Docker Compose** - Container orchestration settings
4. **Application Specifications** - Per-app configuration

## Environment Variables

### Controller Settings

Configure the main Orchestry controller:

```bash
# API Server Configuration
ORCHESTRY_HOST=0.0.0.0              # Bind address (default: 0.0.0.0)
ORCHESTRY_PORT=8000                 # API port (default: 8000)
# ORCHESTRY_WORKERS=4                 # Number of worker processes
ORCHESTRY_LOG_LEVEL=INFO            # Logging level (DEBUG, INFO, WARN, ERROR)

# Controller Settings
CONTROLLER_NODE_ID=controller-1     # Unique node identifier
CONTROLLER_API_URL=http://localhost:8000  # External API URL
CLUSTER_MODE=false                  # Enable cluster mode
```

### Database Configuration

Configure PostgreSQL connection and behavior:

```bash
# Primary Database
POSTGRES_HOST=localhost             # Database host
POSTGRES_PORT=5432                  # Database port
POSTGRES_DB=orchestry              # Database name
POSTGRES_USER=orchestry            # Database username
POSTGRES_PASSWORD=orchestry_password # Database password

# Connection Pool
POSTGRES_POOL_SIZE=10              # Maximum connections
POSTGRES_POOL_TIMEOUT=30           # Connection timeout (seconds)
POSTGRES_RETRY_ATTEMPTS=3          # Connection retry attempts
POSTGRES_RETRY_DELAY=5             # Retry delay (seconds)

# Read Replica (Optional)
POSTGRES_REPLICA_HOST=localhost    # Replica host
POSTGRES_REPLICA_PORT=5433         # Replica port
POSTGRES_READ_ONLY=false           # Force read-only operations to replica
```

### Docker Configuration

Configure Docker daemon integration:

```bash
# Docker Settings
DOCKER_HOST=unix:///var/run/docker.sock  # Docker daemon socket
DOCKER_API_VERSION=auto            # Docker API version
DOCKER_TIMEOUT=60                  # Operation timeout (seconds)

# Container Network
DOCKER_NETWORK=orchestry           # Container network name
DOCKER_SUBNET=172.20.0.0/16       # Network subnet
CONTAINER_CPU_LIMIT=2.0            # Default CPU limit per container
CONTAINER_MEMORY_LIMIT=2Gi         # Default memory limit per container
```

### Scaling Configuration

Configure auto-scaling behavior:

```bash
# Scaling Engine
SCALE_CHECK_INTERVAL=30            # Scaling check interval (seconds)
SCALE_COOLDOWN=180                 # Default cooldown (seconds)
SCALE_MAX_CONCURRENT=3             # Max concurrent scaling operations
SCALE_HISTORY_RETENTION=168        # Hours to retain scaling history

# Default Scaling Policies
DEFAULT_MIN_REPLICAS=1             # Default minimum replicas
DEFAULT_MAX_REPLICAS=5             # Default maximum replicas
DEFAULT_TARGET_RPS=50              # Default target RPS per replica
DEFAULT_MAX_LATENCY=250            # Default max P95 latency (ms)
DEFAULT_MAX_CPU=70                 # Default max CPU % 
DEFAULT_MAX_MEMORY=75              # Default max memory %
```

### Health Check Configuration

Configure health monitoring:

```bash
# Health Check Engine
HEALTH_CHECK_INTERVAL=10           # Health check interval (seconds)
HEALTH_CHECK_TIMEOUT=5             # Health check timeout (seconds)
HEALTH_CHECK_RETRIES=3             # Retries before marking unhealthy
HEALTH_CHECK_PARALLEL=10           # Max parallel health checks

# Default Health Check Settings
DEFAULT_INITIAL_DELAY=30           # Default initial delay (seconds)
DEFAULT_PERIOD=30                  # Default check period (seconds)
DEFAULT_FAILURE_THRESHOLD=3        # Default failure threshold
DEFAULT_SUCCESS_THRESHOLD=1        # Default success threshold
```

### Nginx Configuration

Configure the load balancer:

```bash
# Nginx Settings
NGINX_CONFIG_PATH=/etc/nginx/conf.d # Nginx configuration directory
NGINX_TEMPLATE_PATH=/etc/nginx/templates # Template directory
NGINX_RELOAD_COMMAND="nginx -s reload" # Reload command
NGINX_TEST_COMMAND="nginx -t"      # Configuration test command

# Load Balancing
NGINX_UPSTREAM_METHOD=least_conn   # Load balancing method
NGINX_KEEPALIVE_TIMEOUT=75         # Keepalive timeout
NGINX_KEEPALIVE_REQUESTS=100       # Keepalive requests
NGINX_PROXY_TIMEOUT=60             # Proxy timeout
```

### Metrics and Monitoring

Configure metrics collection:

```bash
# Metrics Collection
METRICS_ENABLED=true               # Enable metrics collection
METRICS_INTERVAL=10                # Collection interval (seconds)
METRICS_RETENTION_HOURS=168        # Hours to retain metrics
METRICS_EXPORT_PORT=9090           # Prometheus export port

# Alerting (Future)
ALERTS_ENABLED=false               # Enable alerting
ALERT_MANAGER_URL=http://localhost:9093 # AlertManager URL
```

## Configuration Files

### Main Configuration File

Create `/etc/orchestry/config.yaml`:

```yaml
# Orchestry Configuration
version: "1.0"

# Controller Configuration
controller:
  host: "0.0.0.0"
  port: 8000
  workers: 4
  log_level: "INFO"
  cluster_mode: false
  node_id: "controller-1"
  api_url: "http://localhost:8000"

# Database Configuration
database:
  primary:
    host: "localhost"
    port: 5432
    name: "orchestry"
    user: "orchestry"
    password: "orchestry_password"
    pool_size: 10
    timeout: 30
  replica:
    enabled: false
    host: "localhost"
    port: 5433
    read_only: false

# Docker Configuration
docker:
  host: "unix:///var/run/docker.sock"
  api_version: "auto"
  timeout: 60
  network: "orchestry"
  subnet: "172.20.0.0/16"
  
# Default Resource Limits
resources:
  default_cpu_limit: "1000m"
  default_memory_limit: "1Gi"
  max_cpu_per_container: "4000m"
  max_memory_per_container: "8Gi"

# Scaling Configuration
scaling:
  check_interval: 30
  default_cooldown: 180
  max_concurrent_operations: 3
  history_retention_hours: 168
  
  # Default Policies
  defaults:
    min_replicas: 1
    max_replicas: 5
    target_rps_per_replica: 50
    max_p95_latency_ms: 250
    max_cpu_percent: 70
    max_memory_percent: 75
    scale_out_threshold_pct: 80
    scale_in_threshold_pct: 30
    window_seconds: 60

# Health Check Configuration
health:
  check_interval: 10
  check_timeout: 5
  max_retries: 3
  parallel_checks: 10
  
  # Default Settings
  defaults:
    initial_delay_seconds: 30
    period_seconds: 30
    failure_threshold: 3
    success_threshold: 1

# Nginx Configuration
nginx:
  config_path: "/etc/nginx/conf.d"
  template_path: "/etc/nginx/templates"
  reload_command: "nginx -s reload"
  test_command: "nginx -t"
  
  # Load Balancing
  upstream_method: "least_conn"
  keepalive_timeout: 75
  keepalive_requests: 100
  proxy_timeout: 60

# Metrics Configuration
metrics:
  enabled: true
  collection_interval: 10
  retention_hours: 168
  export_port: 9090
  
# Logging Configuration
logging:
  level: "INFO"
  format: "json"
  file: "/var/log/orchestry/controller.log"
  max_size_mb: 100
  max_files: 10
  compress: true
```

### Environment-Specific Configuration

#### Development Configuration

Create `.env.development`:

```bash
# Development Environment
NODE_ENV=development
ORCHESTRY_LOG_LEVEL=DEBUG

# Relaxed Settings
SCALE_CHECK_INTERVAL=60
HEALTH_CHECK_INTERVAL=30
DEFAULT_MIN_REPLICAS=1
DEFAULT_MAX_REPLICAS=3

# Local Database
POSTGRES_HOST=localhost
POSTGRES_DB=orchestry_dev

# Development Features
METRICS_ENABLED=false
CLUSTER_MODE=false
```

#### Production Configuration

Create `.env.production`:

```bash
# Production Environment
NODE_ENV=production
ORCHESTRY_LOG_LEVEL=INFO

# Optimized Settings
SCALE_CHECK_INTERVAL=15
HEALTH_CHECK_INTERVAL=10
DEFAULT_MIN_REPLICAS=2
DEFAULT_MAX_REPLICAS=20

# Production Database
POSTGRES_HOST=postgres-cluster.example.com
POSTGRES_DB=orchestry_prod
POSTGRES_POOL_SIZE=20

# High Availability
CLUSTER_MODE=true
METRICS_ENABLED=true
POSTGRES_REPLICA_HOST=postgres-read.example.com
```

#### Staging Configuration

Create `.env.staging`:

```bash
# Staging Environment
NODE_ENV=staging
ORCHESTRY_LOG_LEVEL=INFO

# Moderate Settings
SCALE_CHECK_INTERVAL=30
HEALTH_CHECK_INTERVAL=15
DEFAULT_MIN_REPLICAS=1
DEFAULT_MAX_REPLICAS=10

# Staging Database
POSTGRES_HOST=postgres-staging.example.com
POSTGRES_DB=orchestry_staging

# Testing Features
METRICS_ENABLED=true
CLUSTER_MODE=false
```

## Docker Compose Configuration

### Basic Docker Compose

```yaml
# docker-compose.yml
version: '3.8'

services:
  orchestry-controller:
    build: .
    container_name: orchestry-controller
    environment:
      - ORCHESTRY_HOST=0.0.0.0
      - ORCHESTRY_PORT=8000
      - POSTGRES_HOST=postgres-primary
      - POSTGRES_DB=orchestry
      - POSTGRES_USER=orchestry
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
    ports:
      - "8000:8000"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./logs:/app/logs
    depends_on:
      - postgres-primary
    networks:
      - orchestry
    restart: unless-stopped

  postgres-primary:
    image: postgres:15-alpine
    container_name: orchestry-postgres-primary
    environment:
      POSTGRES_DB: orchestry
      POSTGRES_USER: orchestry
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    networks:
      - orchestry
    restart: unless-stopped

  nginx:
    image: nginx:alpine
    container_name: orchestry-nginx
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./configs/nginx/nginx.conf:/etc/nginx/nginx.conf
      - ./configs/nginx/conf.d:/etc/nginx/conf.d
      - ./ssl:/etc/nginx/ssl
    networks:
      - orchestry
    restart: unless-stopped

volumes:
  postgres_data:

networks:
  orchestry:
    driver: bridge
    ipam:
      config:
        - subnet: 172.20.0.0/16
```

### Production Docker Compose

```yaml
# docker-compose.prod.yml
version: '3.8'

services:
  orchestry-controller:
    image: orchestry:latest
    deploy:
      replicas: 3
      resources:
        limits:
          cpus: '2.0'
          memory: 2G
        reservations:
          cpus: '1.0'
          memory: 1G
    environment:
      - NODE_ENV=production
      - CLUSTER_MODE=true
      - POSTGRES_POOL_SIZE=20
      - SCALE_CHECK_INTERVAL=15
    configs:
      - source: orchestry_config
        target: /etc/orchestry/config.yaml
    secrets:
      - postgres_password
      - api_secret_key
    networks:
      - orchestry
      - monitoring

  postgres-primary:
    image: postgres:15-alpine
    deploy:
      replicas: 1
      resources:
        limits:
          cpus: '4.0'
          memory: 8G
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/postgres_password
    volumes:
      - postgres_primary_data:/var/lib/postgresql/data
    secrets:
      - postgres_password
    networks:
      - orchestry

  postgres-replica:
    image: postgres:15-alpine
    deploy:
      replicas: 2
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/postgres_password
    volumes:
      - postgres_replica_data:/var/lib/postgresql/data
    secrets:
      - postgres_password
    networks:
      - orchestry

  nginx:
    image: nginx:alpine
    deploy:
      replicas: 2
    ports:
      - "80:80"
      - "443:443"
    configs:
      - source: nginx_config
        target: /etc/nginx/nginx.conf
    networks:
      - orchestry
      - external

  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    configs:
      - source: prometheus_config
        target: /etc/prometheus/prometheus.yml
    networks:
      - monitoring

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD__FILE=/run/secrets/grafana_password
    secrets:
      - grafana_password
    networks:
      - monitoring

configs:
  orchestry_config:
    file: ./configs/orchestry/config.yaml
  nginx_config:
    file: ./configs/nginx/nginx.conf
  prometheus_config:
    file: ./configs/prometheus/prometheus.yml

secrets:
  postgres_password:
    external: true
  api_secret_key:
    external: true
  grafana_password:
    external: true

volumes:
  postgres_primary_data:
  postgres_replica_data:

networks:
  orchestry:
    driver: overlay
    attachable: true
  monitoring:
    driver: overlay
  external:
    external: true
```

## Application-Specific Configuration

### Resource Management

Configure resource limits per application type:

```yaml
# High-CPU Application
apiVersion: v1
kind: App
metadata:
  name: cpu-intensive-app
spec:
  type: http
  image: "my-app:latest"
  resources:
    cpu: "4000m"        # 4 CPU cores
    memory: "2Gi"       # 2 GiB memory
scaling:
  mode: auto
  minReplicas: 2
  maxReplicas: 10
  maxCPUPercent: 80     # Scale when CPU > 80%
  targetRPSPerReplica: 25  # Lower RPS due to CPU intensity
```

```yaml
# Memory-Intensive Application
apiVersion: v1
kind: App
metadata:
  name: memory-intensive-app
spec:
  type: http
  image: "my-app:latest"
  resources:
    cpu: "1000m"        # 1 CPU core
    memory: "8Gi"       # 8 GiB memory
scaling:
  mode: auto
  minReplicas: 1
  maxReplicas: 5
  maxMemoryPercent: 85  # Scale when memory > 85%
  targetRPSPerReplica: 100
```

### Environment-Specific Scaling

```yaml
# Development Environment
scaling:
  mode: manual         # Manual scaling only
  minReplicas: 1
  maxReplicas: 2
healthCheck:
  periodSeconds: 60    # Less frequent checks
  initialDelaySeconds: 60
```

```yaml
# Production Environment
scaling:
  mode: auto
  minReplicas: 3       # Always have at least 3
  maxReplicas: 50      # Scale up to 50 replicas
  targetRPSPerReplica: 100
  maxP95LatencyMs: 150 # Strict latency requirements
  scaleOutThresholdPct: 70  # Scale out early
  scaleInThresholdPct: 20   # Scale in conservatively
  cooldownSeconds: 120      # Faster scaling
healthCheck:
  periodSeconds: 10    # Frequent health checks
  failureThreshold: 2  # Fail fast
```

## Security Configuration

### Network Security

```bash
# Network Configuration
DOCKER_NETWORK_DRIVER=bridge      # Network driver
NETWORK_ISOLATION=true            # Enable network isolation
FIREWALL_ENABLED=true             # Enable firewall rules
ALLOWED_CIDR_BLOCKS=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16

# TLS Configuration
TLS_ENABLED=true                  # Enable TLS
TLS_CERT_PATH=/etc/ssl/certs/orchestry.crt
TLS_KEY_PATH=/etc/ssl/private/orchestry.key
TLS_CA_PATH=/etc/ssl/certs/ca.crt
```

### Authentication (Future)

```bash
# Authentication
AUTH_ENABLED=true                 # Enable authentication
AUTH_METHOD=jwt                   # Authentication method
JWT_SECRET_KEY=your-secret-key    # JWT signing key
JWT_EXPIRY=24h                    # Token expiry
```

### RBAC Configuration (Future)

```yaml
# rbac.yaml
apiVersion: v1
kind: RoleBinding
metadata:
  name: admin-binding
subjects:
  - kind: User
    name: admin
    namespace: default
roleRef:
  kind: Role
  name: admin
  apiGroup: rbac.orchestry.io

---
apiVersion: v1
kind: Role
metadata:
  name: developer
rules:
  - apiGroups: [""]
    resources: ["apps"]
    verbs: ["get", "list", "create", "update"]
  - apiGroups: [""]
    resources: ["apps/scale"]
    verbs: ["update"]
```

## Performance Tuning

### Database Optimization

```bash
# PostgreSQL Performance
POSTGRES_SHARED_BUFFERS=256MB     # Shared buffer size
POSTGRES_EFFECTIVE_CACHE_SIZE=1GB # Effective cache size
POSTGRES_WORK_MEM=4MB             # Work memory per query
POSTGRES_MAINTENANCE_WORK_MEM=64MB # Maintenance work memory
POSTGRES_WAL_BUFFERS=16MB         # WAL buffer size
POSTGRES_CHECKPOINT_SEGMENTS=32   # Checkpoint segments
```

### Controller Performance

```bash
# Controller Optimization
ORCHESTRY_WORKERS=8               # Number of worker processes
UVICORN_WORKER_CLASS=uvicorn.workers.UvicornWorker
UVICORN_WORKER_CONNECTIONS=1000   # Connections per worker
UVICORN_BACKLOG=2048             # Listen backlog
UVICORN_KEEPALIVE_TIMEOUT=5      # Keep-alive timeout

# Async Settings
ASYNC_POOL_SIZE=100              # Async connection pool
ASYNC_TIMEOUT=30                 # Async operation timeout
```

### Scaling Performance

```bash
# Scaling Optimization
SCALE_CONCURRENT_LIMIT=5         # Max concurrent scaling ops
SCALE_BATCH_SIZE=3               # Containers to scale per batch  
SCALE_METRICS_CACHE_TTL=10       # Metrics cache TTL (seconds)
HEALTH_CHECK_CACHE_TTL=5         # Health check cache TTL
```

## Monitoring Configuration

### Prometheus Integration

```yaml
# prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'orchestry'
    static_configs:
      - targets: ['orchestry-controller:9090']
    scrape_interval: 10s
    metrics_path: /metrics

  - job_name: 'applications'
    http_sd_configs:
      - url: http://orchestry-controller:8000/api/v1/metrics/targets
    scrape_interval: 30s
```

### Grafana Dashboards

```json
{
  "dashboard": {
    "title": "Orchestry Overview",
    "panels": [
      {
        "title": "Application Count",
        "type": "stat",
        "targets": [
          {
            "expr": "orchestry_applications_total"
          }
        ]
      },
      {
        "title": "Scaling Events",
        "type": "graph",
        "targets": [
          {
            "expr": "rate(orchestry_scaling_events_total[5m])"
          }
        ]
      }
    ]
  }
}
```

## Troubleshooting Configuration

### Debug Settings

```bash
# Enable debug mode
ORCHESTRY_LOG_LEVEL=DEBUG
ORCHESTRY_DEBUG=true
DEBUG_METRICS=true
DEBUG_SCALING=true
DEBUG_HEALTH_CHECKS=true
```

### Common Configuration Issues

**Database Connection Issues:**
```bash
# Check connection
POSTGRES_RETRY_ATTEMPTS=5
POSTGRES_RETRY_DELAY=10
POSTGRES_POOL_TIMEOUT=60
```

**Docker Socket Issues:**
```bash
# Docker socket permissions
DOCKER_HOST=unix:///var/run/docker.sock
# Ensure orchestry user has docker group membership
sudo usermod -aG docker orchestry
```

**Nginx Configuration Issues:**
```bash
# Nginx debugging
NGINX_DEBUG=true
NGINX_ERROR_LOG_LEVEL=debug
# Test configuration
nginx -t -c /etc/nginx/nginx.conf
```

---

**Next Steps**: Learn about [Troubleshooting](troubleshooting.md) for solving common issues.