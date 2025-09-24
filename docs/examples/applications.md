# Sample Applications

Real-world examples of applications deployed with AutoServe, showing different patterns and configurations.

## Web Applications

### Simple Static Website

Perfect for serving static content with automatic scaling based on traffic.

```yaml
# static-website.yml
apiVersion: v1
kind: App
metadata:
  name: my-portfolio
  labels:
    app: "my-portfolio"
    version: "v1.0.0"
    tier: "frontend"
spec:
  type: http
  image: "nginx:alpine"
  ports:
    - containerPort: 80
      protocol: HTTP
  resources:
    cpu: "100m"
    memory: "128Mi"
  volumes:
    - name: "website-content"
      mountPath: "/usr/share/nginx/html"
scaling:
  mode: auto
  minReplicas: 1
  maxReplicas: 10
  targetRPSPerReplica: 100
  maxP95LatencyMs: 200
  scaleOutThresholdPct: 75
  scaleInThresholdPct: 25
healthCheck:
  path: "/"
  port: 80
  initialDelaySeconds: 5
  periodSeconds: 30
```

### Node.js Express API

A typical REST API with database connections and environment configuration.

```yaml
# express-api.yml
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
    - containerPort: 3000
      protocol: HTTP
      name: "api"
    - containerPort: 9090
      protocol: TCP
      name: "metrics"
  resources:
    cpu: "500m"
    memory: "1Gi"
  environment:
    - name: NODE_ENV
      value: "production"
    - name: PORT
      value: "3000"
    - name: INSTANCE_ID
      source: sdk
      key: "instance.ip"
    - name: DATABASE_URL
      value: "postgresql://user:pass@db.example.com:5432/userdb"
    - name: REDIS_URL
      value: "redis://cache.example.com:6379"
    - name: JWT_SECRET
      source: secret
      key: "jwt-credentials"
  healthCheck:
    path: "/api/health"
    port: 3000
    initialDelaySeconds: 30
    periodSeconds: 15
    headers:
      - name: "User-Agent"
        value: "AutoServe-HealthCheck/1.0"
scaling:
  mode: auto
  minReplicas: 2
  maxReplicas: 15
  targetRPSPerReplica: 75
  maxP95LatencyMs: 300
  maxCPUPercent: 70
  maxMemoryPercent: 80
  scaleOutThresholdPct: 80
  scaleInThresholdPct: 30
  cooldownSeconds: 180
```

### React Single Page Application

Frontend application with build process and optimized serving.

```yaml
# react-spa.yml
apiVersion: v1
kind: App
metadata:
  name: dashboard-ui
  labels:
    app: "dashboard-ui"
    version: "v3.2.1"
    tier: "frontend"
spec:
  type: http
  image: "myregistry/dashboard-ui:v3.2.1"
  ports:
    - containerPort: 80
      protocol: HTTP
  resources:
    cpu: "200m"
    memory: "256Mi"
  environment:
    - name: REACT_APP_API_URL
      value: "https://api.example.com"
    - name: REACT_APP_VERSION
      value: "v3.2.1"
    - name: NGINX_WORKER_PROCESSES
      value: "auto"
scaling:
  mode: auto
  minReplicas: 2
  maxReplicas: 8
  targetRPSPerReplica: 150
  maxP95LatencyMs: 150
  scaleOutThresholdPct: 70
  scaleInThresholdPct: 20
healthCheck:
  path: "/health"
  port: 80
  initialDelaySeconds: 10
  periodSeconds: 30
```

## API Services

### Python FastAPI Service

High-performance async API with comprehensive monitoring.

```yaml
# fastapi-service.yml
apiVersion: v1
kind: App
metadata:
  name: analytics-api
  labels:
    app: "analytics-api"
    version: "v1.5.2"
    team: "data"
spec:
  type: http
  image: "myregistry/analytics-api:v1.5.2"
  ports:
    - containerPort: 8000
      protocol: HTTP
      name: "api"
    - containerPort: 8001
      protocol: HTTP
      name: "metrics"
  resources:
    cpu: "1000m"
    memory: "2Gi"
  environment:
    - name: PYTHONPATH
      value: "/app"
    - name: DATABASE_URL
      value: "postgresql://analytics:password@postgres.example.com/analytics"
    - name: REDIS_URL
      value: "redis://redis.example.com:6379/0"
    - name: LOG_LEVEL
      value: "INFO"
    - name: WORKERS
      value: "4"
    - name: INSTANCE_IP
      source: sdk
      key: "instance.ip"
  command: ["uvicorn"]
  args: ["main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
scaling:
  mode: auto
  minReplicas: 3
  maxReplicas: 25
  targetRPSPerReplica: 100
  maxP95LatencyMs: 500
  maxCPUPercent: 75
  maxMemoryPercent: 80
  scaleOutThresholdPct: 75
  scaleInThresholdPct: 25
  cooldownSeconds: 120
healthCheck:
  path: "/health"
  port: 8000
  method: GET
  initialDelaySeconds: 45
  periodSeconds: 20
  timeoutSeconds: 10
  expectedStatusCodes: [200]
```

### Java Spring Boot Application

Enterprise Java application with JVM tuning and monitoring.

```yaml
# spring-boot-api.yml
apiVersion: v1
kind: App
metadata:
  name: order-service
  labels:
    app: "order-service"
    version: "v2.0.5"
    framework: "spring-boot"
spec:
  type: http
  image: "myregistry/order-service:v2.0.5"
  ports:
    - containerPort: 8080
      protocol: HTTP
      name: "api"
    - containerPort: 8081
      protocol: HTTP
      name: "actuator"
  resources:
    cpu: "2000m"
    memory: "4Gi"
  environment:
    - name: SPRING_PROFILES_ACTIVE
      value: "production"
    - name: SERVER_PORT
      value: "8080"
    - name: MANAGEMENT_SERVER_PORT
      value: "8081"
    - name: JAVA_OPTS
      value: "-Xms2g -Xmx3g -XX:+UseG1GC -XX:MaxGCPauseMillis=200"
    - name: DATABASE_URL
      value: "jdbc:postgresql://db.example.com:5432/orders"
    - name: KAFKA_BROKERS
      value: "kafka1.example.com:9092,kafka2.example.com:9092"
scaling:
  mode: auto
  minReplicas: 2
  maxReplicas: 12
  targetRPSPerReplica: 50
  maxP95LatencyMs: 800
  maxCPUPercent: 70
  maxMemoryPercent: 85
  scaleOutThresholdPct: 80
  scaleInThresholdPct: 30
  cooldownSeconds: 300  # Longer cooldown for JVM warmup
healthCheck:
  path: "/actuator/health"
  port: 8081
  initialDelaySeconds: 60  # JVM startup time
  periodSeconds: 30
  timeoutSeconds: 15
  failureThreshold: 5  # Account for GC pauses
```

## Background Workers

### Python Celery Worker

Asynchronous task processing with queue-based scaling.

```yaml
# celery-worker.yml
apiVersion: v1
kind: App
metadata:
  name: email-worker
  labels:
    app: "email-worker"
    version: "v1.3.0"
    type: "worker"
spec:
  type: worker
  image: "myregistry/email-worker:v1.3.0"
  resources:
    cpu: "500m"
    memory: "1Gi"
  environment:
    - name: CELERY_BROKER_URL
      value: "redis://redis.example.com:6379/0"
    - name: CELERY_RESULT_BACKEND
      value: "redis://redis.example.com:6379/1"
    - name: EMAIL_SERVICE_URL
      value: "https://api.sendgrid.com"
    - name: WORKER_CONCURRENCY
      value: "4"
    - name: WORKER_PREFETCH_MULTIPLIER
      value: "1"
  command: ["celery"]
  args: [
    "worker",
    "-A", "tasks",
    "--loglevel=INFO",
    "--concurrency=4",
    "--prefetch-multiplier=1"
  ]
scaling:
  mode: auto
  minReplicas: 2
  maxReplicas: 20
  targetRPSPerReplica: 10  # Lower for background tasks
  maxCPUPercent: 80
  maxMemoryPercent: 75
  scaleOutThresholdPct: 70
  scaleInThresholdPct: 20
  cooldownSeconds: 180
healthCheck:
  # Custom health check for worker
  path: "/health"
  port: 5555  # Flower monitoring port
  initialDelaySeconds: 30
  periodSeconds: 60
```

### Node.js Job Processor

Event-driven job processing with custom metrics.

```yaml
# job-processor.yml
apiVersion: v1
kind: App
metadata:
  name: image-processor
  labels:
    app: "image-processor"
    version: "v2.1.0"
    type: "worker"
spec:
  type: worker
  image: "myregistry/image-processor:v2.1.0"
  resources:
    cpu: "2000m"  # CPU intensive image processing
    memory: "4Gi"
  environment:
    - name: NODE_ENV
      value: "production"
    - name: QUEUE_URL
      value: "amqp://rabbitmq.example.com:5672"
    - name: S3_BUCKET
      value: "image-processing-bucket"
    - name: AWS_REGION
      value: "us-west-2"
    - name: CONCURRENT_JOBS
      value: "2"
    - name: HEALTH_CHECK_PORT
      value: "3001"
  command: ["node"]
  args: ["worker.js"]
scaling:
  mode: auto
  minReplicas: 1
  maxReplicas: 15
  targetRPSPerReplica: 5  # Few concurrent image processing jobs
  maxCPUPercent: 85
  maxMemoryPercent: 80
  scaleOutThresholdPct: 75
  scaleInThresholdPct: 15
  cooldownSeconds: 240
healthCheck:
  path: "/health"
  port: 3001
  initialDelaySeconds: 20
  periodSeconds: 45
```

## Database Services

### PostgreSQL Primary Database

Stateful database service with persistent storage.

```yaml
# postgres-primary.yml
apiVersion: v1
kind: App
metadata:
  name: postgres-primary
  labels:
    app: "postgres-primary"
    version: "v15.3"
    tier: "database"
spec:
  type: tcp
  image: "postgres:15-alpine"
  ports:
    - containerPort: 5432
      protocol: TCP
  resources:
    cpu: "4000m"
    memory: "8Gi"
  environment:
    - name: POSTGRES_DB
      value: "myapp"
    - name: POSTGRES_USER
      value: "myapp"
    - name: POSTGRES_PASSWORD
      source: secret
      key: "postgres-credentials"
      field: "password"
    - name: POSTGRES_INITDB_ARGS
      value: "--auth-host=md5"
    - name: POSTGRES_SHARED_BUFFERS
      value: "2GB"
    - name: POSTGRES_EFFECTIVE_CACHE_SIZE
      value: "6GB"
  volumes:
    - name: "postgres-data"
      mountPath: "/var/lib/postgresql/data"
      size: "100Gi"
    - name: "postgres-config"
      mountPath: "/etc/postgresql"
scaling:
  mode: manual  # Databases typically don't auto-scale
  minReplicas: 1
  maxReplicas: 1
healthCheck:
  port: 5432
  protocol: TCP
  initialDelaySeconds: 60
  periodSeconds: 30
  timeoutSeconds: 10
  failureThreshold: 5
```

### Redis Cache

In-memory cache with persistence configuration.

```yaml
# redis-cache.yml
apiVersion: v1
kind: App
metadata:
  name: redis-cache
  labels:
    app: "redis-cache"
    version: "v7.0"
    tier: "cache"
spec:
  type: tcp
  image: "redis:7.0-alpine"
  ports:
    - containerPort: 6379
      protocol: TCP
  resources:
    cpu: "1000m"
    memory: "4Gi"
  environment:
    - name: REDIS_PASSWORD
      source: secret
      key: "redis-credentials"
    - name: REDIS_MAXMEMORY
      value: "3gb"
    - name: REDIS_MAXMEMORY_POLICY
      value: "allkeys-lru"
  command: ["redis-server"]
  args: [
    "--requirepass", "${REDIS_PASSWORD}",
    "--maxmemory", "${REDIS_MAXMEMORY}",
    "--maxmemory-policy", "${REDIS_MAXMEMORY_POLICY}",
    "--save", "900", "1",
    "--save", "300", "10"
  ]
  volumes:
    - name: "redis-data"
      mountPath: "/data"
      size: "50Gi"
scaling:
  mode: manual
  minReplicas: 1
  maxReplicas: 3  # Can scale for read replicas
healthCheck:
  port: 6379
  protocol: TCP
  initialDelaySeconds: 10
  periodSeconds: 15
```

## Microservices Examples

### E-commerce Order Service

Complete microservice with dependencies and external integrations.

```yaml
# order-service.yml
apiVersion: v1
kind: App
metadata:
  name: order-service
  labels:
    app: "order-service"
    version: "v1.8.2"
    domain: "ecommerce"
    team: "orders"
spec:
  type: http
  image: "myregistry/order-service:v1.8.2"
  ports:
    - containerPort: 8080
      protocol: HTTP
      name: "api"
    - containerPort: 9090
      protocol: HTTP
      name: "metrics"
  resources:
    cpu: "1000m"
    memory: "2Gi"
  environment:
    - name: SPRING_PROFILES_ACTIVE
      value: "production"
    - name: DATABASE_URL
      value: "jdbc:postgresql://postgres.example.com/orders"
    - name: PAYMENT_SERVICE_URL
      value: "https://payment-service.example.com"
    - name: INVENTORY_SERVICE_URL
      value: "https://inventory-service.example.com"
    - name: NOTIFICATION_SERVICE_URL
      value: "https://notification-service.example.com"
    - name: KAFKA_BROKERS
      value: "kafka.example.com:9092"
    - name: REDIS_URL
      value: "redis://redis.example.com:6379"
    - name: JWT_SECRET
      source: secret
      key: "jwt-secret"
scaling:
  mode: auto
  minReplicas: 3
  maxReplicas: 20
  targetRPSPerReplica: 60
  maxP95LatencyMs: 400
  maxCPUPercent: 70
  maxMemoryPercent: 80
  scaleOutThresholdPct: 75
  scaleInThresholdPct: 25
  cooldownSeconds: 180
healthCheck:
  path: "/actuator/health"
  port: 9090
  initialDelaySeconds: 60
  periodSeconds: 30
  timeoutSeconds: 10
  headers:
    - name: "Authorization"
      value: "Bearer health-check-token"
```

### User Authentication Service

Security-focused microservice with enhanced monitoring.

```yaml
# auth-service.yml
apiVersion: v1
kind: App
metadata:
  name: auth-service
  labels:
    app: "auth-service"
    version: "v2.5.1"
    security: "critical"
    team: "security"
spec:
  type: http
  image: "myregistry/auth-service:v2.5.1"
  ports:
    - containerPort: 8080
      protocol: HTTP
  resources:
    cpu: "500m"
    memory: "1Gi"
  environment:
    - name: NODE_ENV
      value: "production"
    - name: JWT_SECRET
      source: secret
      key: "jwt-secret"
    - name: BCRYPT_ROUNDS
      value: "12"
    - name: RATE_LIMIT_WINDOW_MS
      value: "900000"  # 15 minutes
    - name: RATE_LIMIT_MAX_REQUESTS
      value: "5"
    - name: DATABASE_URL
      value: "postgresql://auth:password@postgres.example.com/auth"
    - name: REDIS_URL
      value: "redis://redis.example.com:6379/2"
scaling:
  mode: auto
  minReplicas: 4  # High availability for auth
  maxReplicas: 15
  targetRPSPerReplica: 30  # Lower due to crypto operations
  maxP95LatencyMs: 300
  maxCPUPercent: 65  # Conservative for security service
  scaleOutThresholdPct: 70
  scaleInThresholdPct: 30
  cooldownSeconds: 240
healthCheck:
  path: "/health"
  port: 8080
  initialDelaySeconds: 30
  periodSeconds: 20
  timeoutSeconds: 5
  failureThreshold: 3
  successThreshold: 1
```

## Development and Testing

### Development Environment App

Relaxed configuration for development and testing.

```yaml
# dev-app.yml
apiVersion: v1
kind: App
metadata:
  name: dev-api
  labels:
    app: "dev-api"
    version: "latest"
    environment: "development"
spec:
  type: http
  image: "myregistry/my-api:latest"
  ports:
    - containerPort: 3000
      protocol: HTTP
  resources:
    cpu: "200m"
    memory: "512Mi"
  environment:
    - name: NODE_ENV
      value: "development"
    - name: DEBUG
      value: "*"
    - name: DATABASE_URL
      value: "postgresql://dev:dev@postgres-dev.example.com/devdb"
scaling:
  mode: manual  # Manual scaling for development
  minReplicas: 1
  maxReplicas: 2
healthCheck:
  path: "/health"
  port: 3000
  initialDelaySeconds: 10
  periodSeconds: 60  # Less frequent in dev
  failureThreshold: 10  # More tolerant in dev
```

### Load Testing Application

Application specifically configured for load testing scenarios.

```yaml
# load-test-target.yml
apiVersion: v1
kind: App
metadata:
  name: load-test-app
  labels:
    app: "load-test-app"
    version: "v1.0.0"
    purpose: "testing"
spec:
  type: http
  image: "nginx:alpine"
  ports:
    - containerPort: 80
      protocol: HTTP
  resources:
    cpu: "100m"
    memory: "64Mi"
  environment:
    - name: NGINX_WORKER_PROCESSES
      value: "1"
scaling:
  mode: auto
  minReplicas: 1
  maxReplicas: 50  # Allow high scaling for load tests
  targetRPSPerReplica: 200
  maxP95LatencyMs: 100
  scaleOutThresholdPct: 60  # Scale out early
  scaleInThresholdPct: 10   # Scale in late
  cooldownSeconds: 30       # Fast scaling for tests
healthCheck:
  path: "/"
  port: 80
  initialDelaySeconds: 2
  periodSeconds: 5
```

## Advanced Patterns

### Multi-Container Application

Application with sidecar containers for logging and monitoring.

```yaml
# app-with-sidecars.yml
apiVersion: v1
kind: App
metadata:
  name: monitored-app
  labels:
    app: "monitored-app"
    version: "v1.0.0"
    monitoring: "enhanced"
spec:
  type: http
  image: "myregistry/my-app:v1.0.0"
  ports:
    - containerPort: 8080
      protocol: HTTP
      name: "app"
  resources:
    cpu: "1000m"
    memory: "2Gi"
  sidecars:
    - name: "log-shipper"
      image: "fluent/fluent-bit:latest"
      resources:
        cpu: "100m"
        memory: "128Mi"
      volumes:
        - name: "app-logs"
          mountPath: "/var/log/app"
          shared: true
    - name: "metrics-exporter"
      image: "prom/node-exporter:latest"
      ports:
        - containerPort: 9100
          protocol: HTTP
      resources:
        cpu: "50m"
        memory: "64Mi"
  environment:
    - name: LOG_LEVEL
      value: "INFO"
    - name: METRICS_ENABLED
      value: "true"
scaling:
  mode: auto
  minReplicas: 2
  maxReplicas: 10
  targetRPSPerReplica: 50
healthCheck:
  path: "/health"
  port: 8080
  initialDelaySeconds: 30
  periodSeconds: 20
```

### Blue-Green Deployment

Configuration for blue-green deployment pattern.

```yaml
# blue-green-app.yml
apiVersion: v1
kind: App
metadata:
  name: production-app-blue
  labels:
    app: "production-app"
    version: "v2.0.0"
    deployment: "blue"
    environment: "production"
spec:
  type: http
  image: "myregistry/production-app:v2.0.0"
  ports:
    - containerPort: 8080
      protocol: HTTP
  resources:
    cpu: "1000m"
    memory: "2Gi"
  environment:
    - name: DEPLOYMENT_SLOT
      value: "blue"
    - name: DATABASE_URL
      value: "postgresql://prod:password@db.example.com/prod"
scaling:
  mode: auto
  minReplicas: 5
  maxReplicas: 20
  targetRPSPerReplica: 75
  maxP95LatencyMs: 200
  scaleOutThresholdPct: 75
  scaleInThresholdPct: 25
healthCheck:
  path: "/health"
  port: 8080
  initialDelaySeconds: 45
  periodSeconds: 15
  headers:
    - name: "X-Health-Check"
      value: "blue-deployment"
```

## Monitoring and Observability

### Application with Custom Metrics

Application configured for comprehensive monitoring.

```yaml
# monitored-service.yml
apiVersion: v1
kind: App
metadata:
  name: analytics-service
  labels:
    app: "analytics-service"
    version: "v1.2.0"
    monitoring: "comprehensive"
spec:
  type: http
  image: "myregistry/analytics-service:v1.2.0"  
  ports:
    - containerPort: 8080
      protocol: HTTP
      name: "api"
    - containerPort: 9090
      protocol: HTTP
      name: "metrics"
    - containerPort: 8081
      protocol: HTTP
      name: "health"
  resources:
    cpu: "2000m"
    memory: "4Gi"
  environment:
    - name: METRICS_PORT
      value: "9090"
    - name: HEALTH_PORT
      value: "8081"
    - name: ENABLE_DETAILED_METRICS
      value: "true"
    - name: JAEGER_ENDPOINT
      value: "http://jaeger.example.com:14268/api/traces"
    - name: PROMETHEUS_ENDPOINT
      value: "http://prometheus.example.com:9090"
scaling:
  mode: auto
  minReplicas: 3
  maxReplicas: 25
  targetRPSPerReplica: 80
  maxP95LatencyMs: 400
  customMetrics:
    - name: "queue_length"
      target: 10
      query: "queue_length{service='analytics-service'}"
    - name: "error_rate"
      target: 0.01  # 1% error rate
      query: "rate(http_requests_total{status=~'5..'}[5m])"
healthCheck:
  path: "/health/live"
  port: 8081
  initialDelaySeconds: 60
  periodSeconds: 20
  timeoutSeconds: 10
```

These examples demonstrate various patterns and configurations for different types of applications. Each example includes:

- Appropriate resource allocation
- Environment-specific configuration
- Scaling policies tailored to the application type
- Health checks optimized for the service
- Security and monitoring considerations

---

**Next Steps**: Explore [Deployment Scenarios](deployments.md) for different infrastructure patterns.