# Application Specification

Learn how to define applications for AutoServe using YAML or JSON specifications.

## Overview

AutoServe uses declarative specifications to define how your applications should be deployed, scaled, and monitored. These specifications are written in YAML or JSON format and contain all the information needed to run your application.

## Basic Structure

```yaml
apiVersion: v1
kind: App
metadata:
  name: my-application
  labels:
    app: "my-application"
    version: "v1"
    environment: "production"
spec:
  # Application configuration
  type: http
  image: "my-app:latest"
  ports: []
  resources: {}
  environment: []
scaling:
  # Scaling configuration
  mode: auto
  minReplicas: 1
  maxReplicas: 5
healthCheck:
  # Health check configuration
  path: "/health"
  port: 8080
```

## Complete Reference

### Root Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `apiVersion` | string | Yes | API version (currently `v1`) |
| `kind` | string | Yes | Resource type (currently `App`) |
| `metadata` | object | Yes | Application metadata |
| `spec` | object | Yes | Application specification |
| `scaling` | object | No | Scaling configuration |
| `healthCheck` | object | No | Health check configuration |

### Metadata

The `metadata` section contains information about your application:

```yaml
metadata:
  name: my-web-app              # Required: DNS-compatible name
  labels:
    app: "my-web-app"          # Required: Application identifier
    version: "v1.2.3"          # Recommended: Version tag
    environment: "production"   # Optional: Environment label
    team: "backend"            # Optional: Team ownership
    tier: "web"                # Optional: Application tier
```

**Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Unique application name (DNS-compatible) |
| `labels` | object | Yes | Key-value labels for organization |
| `labels.app` | string | Yes | Application identifier (must match name) |

**Label Restrictions:**
- Must be DNS-compatible (lowercase, alphanumeric, hyphens)
- Maximum 63 characters per label value
- Cannot start or end with hyphens

### Application Spec

The `spec` section defines how your application runs:

```yaml
spec:
  type: http                    # Application type
  image: "nginx:alpine"         # Container image
  ports:                        # Port configuration
    - containerPort: 80
      protocol: HTTP
  resources:                    # Resource limits
    cpu: "500m"
    memory: "512Mi"
  environment:                  # Environment variables
    - name: NODE_ENV
      value: "production"
    - name: DATABASE_URL
      value: "postgresql://..."
  command: ["/bin/sh"]          # Optional: Override entrypoint
  args: ["-c", "nginx -g 'daemon off;'"]  # Optional: Command arguments
  workingDir: "/app"            # Optional: Working directory
  volumes:                      # Optional: Volume mounts
    - name: "app-data"
      mountPath: "/data"
```

#### Application Types

| Type | Description | Use Cases |
|------|-------------|-----------|
| `http` | HTTP web applications | Web servers, APIs, SPAs |
| `tcp` | TCP applications | Databases, message queues |
| `worker` | Background workers | Job processors, daemons |

#### Ports Configuration

```yaml
ports:
  - containerPort: 8080         # Port inside container
    protocol: HTTP              # Protocol (HTTP, TCP)
    name: "web"                 # Optional: Port name
  - containerPort: 9090
    protocol: TCP
    name: "metrics"
```

**Protocol Types:**
- `HTTP`: For web applications (enables load balancing)
- `TCP`: For TCP services (port forwarding only)

#### Resources

Define CPU and memory limits:

```yaml
resources:
  cpu: "500m"      # 500 millicores (0.5 CPU)
  memory: "1Gi"    # 1 GiB memory
```

**CPU Units:**
- `100m` = 0.1 CPU core
- `1` = 1 CPU core
- `2.5` = 2.5 CPU cores

**Memory Units:**
- `128Mi` = 128 MiB
- `1Gi` = 1 GiB
- `512M` = 512 MB

#### Environment Variables

```yaml
environment:
  # Static value
  - name: NODE_ENV
    value: "production"
  
  # AutoServe-provided values
  - name: INSTANCE_IP
    source: sdk
    key: "instance.ip"
  
  # From secrets (future feature)
  - name: DB_PASSWORD
    source: secret
    key: "database-credentials"
    field: "password"
```

**SDK-Provided Variables:**

| Key | Description | Example Value |
|-----|-------------|---------------|
| `instance.ip` | Container IP address | `172.20.0.5` |
| `instance.port` | Primary container port | `8080` |
| `app.name` | Application name | `my-web-app` |
| `app.replicas` | Current replica count | `3` |

#### Volumes (Future Feature)

```yaml
volumes:
  - name: "app-data"
    mountPath: "/data"
    size: "10Gi"
    storageClass: "fast"
  - name: "config"
    mountPath: "/etc/config"
    configMap: "app-config"
```

### Scaling Configuration

Control how your application scales:

```yaml
scaling:
  mode: auto                    # Scaling mode: auto, manual
  minReplicas: 1               # Minimum replicas
  maxReplicas: 10              # Maximum replicas
  
  # Auto-scaling thresholds
  targetRPSPerReplica: 50      # Target requests per second per replica
  maxP95LatencyMs: 250         # Maximum 95th percentile latency
  maxCPUPercent: 70            # Maximum CPU utilization
  maxMemoryPercent: 75         # Maximum memory utilization
  maxConnPerReplica: 100       # Maximum connections per replica
  
  # Scaling behavior
  scaleOutThresholdPct: 80     # Scale out when metrics exceed this %
  scaleInThresholdPct: 30      # Scale in when metrics below this %
  windowSeconds: 60            # Metrics evaluation window
  cooldownSeconds: 180         # Minimum time between scaling events
```

#### Scaling Modes

| Mode | Description | When to Use |
|------|-------------|-------------|
| `auto` | Automatic scaling based on metrics | Production workloads |
| `manual` | Manual scaling only | Development, controlled environments |

#### Scaling Metrics

AutoServe scales based on multiple metrics:

1. **CPU Utilization**: Target 70% average across replicas
2. **Memory Usage**: Target 75% average across replicas  
3. **Requests Per Second**: Target 50 RPS per replica
4. **Response Latency**: Keep P95 latency under 250ms
5. **Active Connections**: Target 100 connections per replica

#### Scaling Behavior

```yaml
scaling:
  # Threshold configuration
  scaleOutThresholdPct: 80     # Scale out when any metric > 80% of target
  scaleInThresholdPct: 30      # Scale in when all metrics < 30% of target
  
  # Timing configuration
  windowSeconds: 60            # Evaluate metrics over 60 seconds
  cooldownSeconds: 180         # Wait 3 minutes between scaling actions
  
  # Advanced settings (optional)
  maxScaleOutStep: 2           # Maximum replicas to add at once
  maxScaleInStep: 1            # Maximum replicas to remove at once
  stabilizationWindowSeconds: 300  # Wait for stability after scaling
```

### Health Check Configuration

Define how AutoServe monitors your application health:

```yaml
healthCheck:
  path: "/health"               # Health check endpoint
  port: 8080                   # Health check port
  protocol: HTTP               # Protocol (HTTP, TCP)
  method: GET                  # HTTP method (GET, POST)
  
  # Timing configuration
  initialDelaySeconds: 30      # Wait before first check
  periodSeconds: 10            # Check interval
  timeoutSeconds: 5            # Request timeout
  
  # Failure handling
  failureThreshold: 3          # Failures before marking unhealthy
  successThreshold: 1          # Successes before marking healthy
  
  # Advanced options
  headers:                     # Custom headers
    - name: "Authorization"
      value: "Bearer token"
  expectedStatusCodes: [200, 204]  # Expected HTTP status codes
```

#### Health Check Types

**HTTP Health Checks:**

```yaml
healthCheck:
  path: "/api/health"
  port: 8080
  protocol: HTTP
  method: GET
  expectedStatusCodes: [200]
  headers:
    - name: "User-Agent"
      value: "AutoServe-HealthCheck/1.0"
```

**TCP Health Checks:**

```yaml
healthCheck:
  port: 5432
  protocol: TCP
  timeoutSeconds: 3
```

**Custom Health Checks:**

```yaml
healthCheck:
  path: "/health/detailed"
  port: 8080
  protocol: HTTP
  method: POST
  headers:
    - name: "Content-Type"
      value: "application/json"
  body: '{"check": "full"}'
  expectedStatusCodes: [200, 202]
```

## Complete Examples

### Simple Web Application

```yaml
apiVersion: v1
kind: App
metadata:
  name: simple-web
  labels:
    app: "simple-web"
    version: "v1"
spec:
  type: http
  image: "nginx:alpine"
  ports:
    - containerPort: 80
      protocol: HTTP
  resources:
    cpu: "100m"
    memory: "128Mi"
scaling:
  mode: auto
  minReplicas: 1
  maxReplicas: 3
  targetRPSPerReplica: 100
healthCheck:
  path: "/"
  port: 80
  initialDelaySeconds: 5
  periodSeconds: 30
```

### Production API Service

```yaml
apiVersion: v1
kind: App
metadata:
  name: user-api
  labels:
    app: "user-api"
    version: "v2.1.0"
    environment: "production"
    team: "backend"
spec:
  type: http
  image: "myregistry/user-api:v2.1.0"
  ports:
    - containerPort: 8080
      protocol: HTTP
      name: "api"
    - containerPort: 9090
      protocol: TCP
      name: "metrics"
  resources:
    cpu: "1000m"
    memory: "2Gi"
  environment:
    - name: NODE_ENV
      value: "production"
    - name: PORT
      value: "8080"
    - name: DATABASE_URL
      source: secret
      key: "database-credentials"
    - name: REDIS_URL
      source: secret
      key: "redis-credentials"
    - name: INSTANCE_IP
      source: sdk
      key: "instance.ip"
scaling:
  mode: auto
  minReplicas: 3
  maxReplicas: 20
  targetRPSPerReplica: 100
  maxP95LatencyMs: 200
  maxCPUPercent: 70
  maxMemoryPercent: 80
  scaleOutThresholdPct: 75
  scaleInThresholdPct: 25
  windowSeconds: 120
  cooldownSeconds: 300
healthCheck:
  path: "/api/v2/health"
  port: 8080
  protocol: HTTP
  method: GET
  initialDelaySeconds: 45
  periodSeconds: 15
  timeoutSeconds: 10
  failureThreshold: 3
  successThreshold: 1
  headers:
    - name: "Authorization"
      value: "Bearer health-check-token"
  expectedStatusCodes: [200]
```

### Background Worker

```yaml
apiVersion: v1
kind: App
metadata:
  name: email-worker
  labels:
    app: "email-worker"
    version: "v1.0.0"
    tier: "worker"
spec:
  type: worker
  image: "myregistry/email-worker:v1.0.0"
  resources:
    cpu: "500m"
    memory: "1Gi"
  environment:
    - name: QUEUE_URL
      source: secret
      key: "queue-credentials"
    - name: WORKER_CONCURRENCY
      value: "5"
  command: ["/app/worker"]
  args: ["--queue", "emails", "--concurrency", "5"]
scaling:
  mode: manual
  minReplicas: 2
  maxReplicas: 10
healthCheck:
  port: 8080
  path: "/health"
  protocol: HTTP
  initialDelaySeconds: 30
  periodSeconds: 30
```

### Database Service

```yaml
apiVersion: v1
kind: App
metadata:
  name: postgres-db
  labels:
    app: "postgres-db"
    version: "v13"
    tier: "database"
spec:
  type: tcp
  image: "postgres:13-alpine"
  ports:
    - containerPort: 5432
      protocol: TCP
  resources:
    cpu: "2000m"
    memory: "4Gi"
  environment:
    - name: POSTGRES_DB
      value: "myapp"
    - name: POSTGRES_USER
      source: secret
      key: "postgres-credentials"
      field: "username"
    - name: POSTGRES_PASSWORD
      source: secret
      key: "postgres-credentials"
      field: "password"
  volumes:
    - name: "postgres-data"
      mountPath: "/var/lib/postgresql/data"
      size: "100Gi"
scaling:
  mode: manual
  minReplicas: 1
  maxReplicas: 1
healthCheck:
  port: 5432
  protocol: TCP
  initialDelaySeconds: 60
  periodSeconds: 30
  timeoutSeconds: 5
  failureThreshold: 5
```

## Validation Rules

AutoServe validates specifications before deployment:

### Required Fields

- `apiVersion`: Must be `v1`
- `kind`: Must be `App`
- `metadata.name`: Must be DNS-compatible
- `metadata.labels.app`: Must match `metadata.name`
- `spec.type`: Must be `http`, `tcp`, or `worker`
- `spec.image`: Must be a valid container image reference

### Naming Conventions

**Application Names:**
- Lowercase letters, numbers, and hyphens only
- Must start and end with alphanumeric character
- Maximum 253 characters
- Must be unique within AutoServe instance

**Label Values:**
- Same rules as application names
- Maximum 63 characters

### Resource Limits

**CPU:**
- Minimum: `10m` (0.01 CPU)
- Maximum: `16` (16 CPUs)
- Must be positive number

**Memory:**
- Minimum: `64Mi` (64 MiB)
- Maximum: `64Gi` (64 GiB)
- Must be positive number

### Scaling Limits

- `minReplicas`: 1-100
- `maxReplicas`: 1-100, must be ≥ `minReplicas`
- `targetRPSPerReplica`: 1-10000
- `maxP95LatencyMs`: 1-30000
- Percentages: 1-100

## Best Practices

### Application Design

1. **Stateless Applications**: Design apps to be stateless for easy scaling
2. **Health Endpoints**: Always provide meaningful health check endpoints
3. **Graceful Shutdown**: Handle SIGTERM signals for graceful shutdown
4. **Resource Limits**: Set appropriate CPU and memory limits
5. **Environment Configuration**: Use environment variables for configuration

### Scaling Configuration

1. **Conservative Limits**: Start with conservative scaling limits
2. **Monitoring**: Monitor scaling behavior and adjust thresholds
3. **Cooldown Periods**: Use appropriate cooldown periods to prevent flapping
4. **Multiple Metrics**: Don't rely on a single metric for scaling decisions

### Production Readiness

1. **Health Checks**: Configure comprehensive health checks
2. **Resource Monitoring**: Set up monitoring and alerting
3. **Version Tags**: Always use specific version tags, not `latest`
4. **Security**: Use minimal base images and security scanning
5. **Backup Strategy**: Plan for data backup and recovery

### Development Workflow

1. **Validate Locally**: Test specifications locally before deployment
2. **Version Control**: Store specifications in version control
3. **Environment Promotion**: Use different specifications per environment
4. **Documentation**: Document application-specific configuration

## Troubleshooting

### Common Validation Errors

**Invalid Name:**
```
Error: metadata.name must be DNS-compatible
Solution: Use lowercase letters, numbers, and hyphens only
```

**Missing Required Fields:**
```
Error: spec.image is required
Solution: Add image field to spec section
```

**Invalid Resource Format:**
```
Error: resources.cpu must be a valid quantity (e.g., "500m", "1")
Solution: Use proper CPU units (millicores or cores)
```

**Scaling Configuration Issues:**
```
Error: scaling.maxReplicas must be >= scaling.minReplicas
Solution: Ensure maxReplicas is greater than or equal to minReplicas
```

### Deployment Issues

**Image Pull Errors:**
- Verify image exists and is accessible
- Check registry credentials
- Use full image path with registry

**Health Check Failures:**
- Verify health endpoint is accessible
- Check port configuration
- Increase initial delay if needed

**Resource Constraints:**
- Monitor actual resource usage
- Adjust limits based on application needs
- Consider node capacity limits

---

**Next Steps**: Learn about [Configuration and Environment Variables](configuration.md) for advanced settings.