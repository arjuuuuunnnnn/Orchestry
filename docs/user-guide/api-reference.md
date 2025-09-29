# REST API Reference

Complete reference for the Orchestry REST API endpoints.

## Base URL

```
http://localhost:8000
```

## Authentication

Currently, Orchestry does not require authentication. This will be added in future versions.

## Content Types

- **Request**: `application/json`
- **Response**: `application/json`

## Error Responses

All API endpoints return consistent error responses:

```json
{
  "error": "Application not found",
  "details": "Application 'my-app' does not exist",
  "code": "APP_NOT_FOUND",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

**HTTP Status Codes:**
- `200` - Success
- `201` - Created
- `400` - Bad Request
- `404` - Not Found
- `409` - Conflict
- `500` - Internal Server Error
- `503` - Service Unavailable

## Application Management

### Register Application

Register a new application from specification.

```http
POST /api/v1/apps/register
Content-Type: application/json

{
  "apiVersion": "v1",
  "kind": "App",
  "metadata": {
    "name": "my-app",
    "labels": {
      "app": "my-app",
      "version": "v1"
    }
  },
  "spec": {
    "type": "http",
    "image": "nginx:alpine",
    "ports": [
      {
        "containerPort": 80,
        "protocol": "HTTP"
      }
    ]
  }
}
```

**Response:**
```json
{
  "message": "Application registered successfully",
  "app_name": "my-app",
  "status": "registered"
}
```

### Start Application

Start a registered application.

```http
POST /api/v1/apps/{app_name}/start
```

**Parameters:**
- `app_name` (path): Application name

**Request Body (optional):**
```json
{
  "replicas": 3,
  "wait": true,
  "timeout": 300
}
```

**Response:**
```json
{
  "message": "Application started successfully",
  "app_name": "my-app",
  "replicas": 3,
  "status": "running"
}
```

### Stop Application

Stop a running application.

```http
POST /api/v1/apps/{app_name}/stop
```

**Parameters:**
- `app_name` (path): Application name

**Request Body (optional):**
```json
{
  "force": false,
  "timeout": 30
}
```

**Response:**
```json
{
  "message": "Application stopped successfully",
  "app_name": "my-app",
  "status": "stopped"
}
```

### Scale Application

Scale an application to specific replica count.

```http
POST /api/v1/apps/{app_name}/scale
```

**Parameters:**
- `app_name` (path): Application name

**Request Body:**
```json
{
  "replicas": 5,
  "wait": true,
  "timeout": 300
}
```

**Response:**
```json
{
  "message": "Application scaled successfully",
  "app_name": "my-app",
  "previous_replicas": 3,
  "current_replicas": 5,
  "scaling_time": 45.2
}
```

### Remove Application

Remove an application and all its resources.

```http
DELETE /api/v1/apps/{app_name}
```

**Parameters:**
- `app_name` (path): Application name

**Query Parameters:**
- `force` (boolean): Skip confirmation
- `keep_data` (boolean): Keep persistent volumes

**Response:**
```json
{
  "message": "Application removed successfully",
  "app_name": "my-app",
  "containers_removed": 3,
  "volumes_removed": 1
}
```

## Application Information

### Get Application Status

Get detailed status of a specific application.

```http
GET /api/v1/apps/{app_name}
```

**Parameters:**
- `app_name` (path): Application name

**Response:**
```json
{
  "name": "my-app",
  "status": "running",
  "replicas": {
    "current": 3,
    "desired": 3,
    "healthy": 3
  },
  "metrics": {
    "cpu_percent": 45.2,
    "memory_percent": 62.1,
    "rps": 127.5,
    "latency_p95_ms": 89,
    "active_connections": 234
  },
  "created_at": "2024-01-15T08:00:00Z",
  "updated_at": "2024-01-15T10:30:00Z",
  "last_scaled_at": "2024-01-15T09:15:00Z",
  "containers": [
    {
      "id": "abc123",
      "name": "my-app-1",
      "ip": "172.20.0.5",
      "port": 80,
      "status": "running",
      "health": "healthy",
      "started_at": "2024-01-15T09:00:00Z"
    }
  ]
}
```

### List Applications

List all registered applications.

```http
GET /api/v1/apps
```

**Query Parameters:**
- `status` (string): Filter by status (`running`, `stopped`, `error`)
- `format` (string): Response format (`json`, `summary`)

**Response:**
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
      "image": "nginx:alpine",
      "created_at": "2024-01-15T08:00:00Z"
    },
    {
      "name": "api-service",
      "status": "running", 
      "replicas": {
        "current": 5,
        "desired": 5
      },
      "image": "myapp/api:v2.1.0",
      "created_at": "2024-01-14T15:30:00Z"
    }
  ],
  "total": 2,
  "running": 2,
  "stopped": 0,
  "error": 0
}
```

### Get Application Specification

Retrieve the original application specification.

```http
GET /api/v1/apps/{app_name}/spec
```

**Parameters:**
- `app_name` (path): Application name

**Response:**
```json
{
  "apiVersion": "v1",
  "kind": "App",
  "metadata": {
    "name": "my-app",
    "labels": {
      "app": "my-app",
      "version": "v1"
    }
  },
  "spec": {
    "type": "http",
    "image": "nginx:alpine",
    "ports": [
      {
        "containerPort": 80,
        "protocol": "HTTP"
      }
    ]
  },
  "scaling": {
    "mode": "auto",
    "minReplicas": 1,
    "maxReplicas": 5
  }
}
```

## Monitoring and Metrics

### Get Application Metrics

Get current performance metrics for an application.

```http
GET /api/v1/apps/{app_name}/metrics
```

**Parameters:**
- `app_name` (path): Application name

**Query Parameters:**
- `history` (integer): Number of historical data points (default: 10)
- `interval` (string): Time interval (`5m`, `1h`, `1d`)

**Response:**
```json
{
  "app_name": "my-app",
  "timestamp": "2024-01-15T10:30:00Z",
  "current": {
    "cpu_percent": 45.2,
    "memory_percent": 62.1,
    "rps": 127.5,
    "latency_p95_ms": 89,
    "active_connections": 234,
    "healthy_replicas": 3,
    "total_replicas": 3
  },
  "history": [
    {
      "timestamp": "2024-01-15T10:25:00Z",
      "cpu_percent": 42.1,
      "memory_percent": 58.9,
      "rps": 115.2,
      "latency_p95_ms": 92
    }
  ]
}
```

### Get Application Events

Get event history for an application.

```http
GET /api/v1/apps/{app_name}/events
```

**Parameters:**
- `app_name` (path): Application name

**Query Parameters:**
- `type` (string): Event type filter (`scaling`, `health`, `config`, `error`)
- `since` (string): Time filter (`1h`, `1d`, ISO timestamp)
- `limit` (integer): Maximum events to return (default: 100)

**Response:**
```json
{
  "app_name": "my-app",
  "events": [
    {
      "id": 123,
      "type": "scaling",
      "message": "Scaled from 2 to 3 replicas due to high CPU usage",
      "timestamp": "2024-01-15T09:15:00Z",
      "details": {
        "previous_replicas": 2,
        "new_replicas": 3,
        "trigger": "cpu_high",
        "cpu_percent": 78.5
      }
    },
    {
      "id": 122,
      "type": "health",
      "message": "Container my-app-2 marked as unhealthy",
      "timestamp": "2024-01-15T08:45:00Z",
      "details": {
        "container_id": "def456",
        "health_check_failures": 3
      }
    }
  ],
  "total": 25,
  "has_more": true
}
```

### Get Application Logs

Get container logs for an application.

```http
GET /api/v1/apps/{app_name}/logs
```

**Parameters:**
- `app_name` (path): Application name

**Query Parameters:**
- `container` (string): Specific container name
- `tail` (integer): Number of lines from end (default: 100)
- `since` (string): Time filter (`1h`, `1d`, ISO timestamp)
- `follow` (boolean): Stream logs (WebSocket upgrade)

**Response:**
```json
{
  "app_name": "my-app",
  "logs": [
    {
      "timestamp": "2024-01-15T10:30:15Z",
      "container": "my-app-1",
      "level": "INFO",
      "message": "Request processed successfully"
    },
    {
      "timestamp": "2024-01-15T10:30:10Z", 
      "container": "my-app-2",
      "level": "WARN",
      "message": "High memory usage detected"
    }
  ],
  "total_lines": 1543,
  "has_more": true
}
```

## Scaling Management

### Get Scaling Policy

Get the current scaling policy for an application.

```http
GET /api/v1/apps/{app_name}/scaling
```

**Response:**
```json
{
  "app_name": "my-app",
  "mode": "auto",
  "policy": {
    "min_replicas": 1,
    "max_replicas": 5,
    "target_rps_per_replica": 50,
    "max_p95_latency_ms": 250,
    "max_cpu_percent": 70.0,
    "max_memory_percent": 75.0,
    "scale_out_threshold_pct": 80,
    "scale_in_threshold_pct": 30,
    "window_seconds": 60,
    "cooldown_seconds": 180
  },
  "last_scaling_event": {
    "timestamp": "2024-01-15T09:15:00Z",
    "action": "scale_out",
    "from_replicas": 2,
    "to_replicas": 3,
    "reason": "High CPU usage: 78.5%"
  }
}
```

### Update Scaling Policy

Update the scaling policy for an application.

```http
PUT /api/v1/apps/{app_name}/scaling
```

**Request Body:**
```json
{
  "mode": "auto",
  "min_replicas": 2,
  "max_replicas": 10,
  "target_rps_per_replica": 100,
  "max_p95_latency_ms": 200,
  "scale_out_threshold_pct": 75,
  "scale_in_threshold_pct": 25
}
```

**Response:**
```json
{
  "message": "Scaling policy updated successfully",
  "app_name": "my-app",
  "previous_policy": {
    "min_replicas": 1,
    "max_replicas": 5
  },
  "new_policy": {
    "min_replicas": 2,
    "max_replicas": 10
  }
}
```

## Health Management

### Get Health Status

Get detailed health status for an application.

```http
GET /api/v1/apps/{app_name}/health
```

**Response:**
```json
{
  "app_name": "my-app",
  "overall_health": "healthy",
  "healthy_replicas": 3,
  "total_replicas": 3,
  "containers": [
    {
      "id": "abc123",
      "name": "my-app-1",
      "health": "healthy",
      "last_check": "2024-01-15T10:30:00Z",
      "consecutive_failures": 0,
      "response_time_ms": 45
    },
    {
      "id": "def456", 
      "name": "my-app-2",
      "health": "unhealthy",
      "last_check": "2024-01-15T10:29:30Z",
      "consecutive_failures": 2,
      "last_error": "Connection refused"
    }
  ],
  "health_check_config": {
    "path": "/health",
    "port": 80,
    "protocol": "HTTP",
    "period_seconds": 30,
    "timeout_seconds": 5,
    "failure_threshold": 3
  }
}
```

### Trigger Health Check

Manually trigger health checks for an application.

```http
POST /api/v1/apps/{app_name}/health/check
```

**Response:**
```json
{
  "message": "Health check triggered",
  "app_name": "my-app",
  "containers_checked": 3,
  "healthy": 2,
  "unhealthy": 1
}
```

## System Information

### System Health

Get overall system health status.

```http
GET /health
```

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00Z",
  "version": "1.0.0",
  "uptime_seconds": 86400,
  "components": {
    "database": {
      "status": "healthy",
      "response_time_ms": 12
    },
    "docker": {
      "status": "healthy",
      "containers_running": 15
    },
    "nginx": {
      "status": "healthy",
      "configs_active": 5
    }
  },
  "applications": {
    "total": 8,
    "running": 6,
    "stopped": 1,
    "error": 1
  }
}
```

### System Metrics

Get system-wide metrics and statistics.

```http
GET /api/v1/metrics
```

**Response:**
```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "system": {
    "cpu_percent": 35.2,
    "memory_used_gb": 12.5,
    "memory_total_gb": 32.0,
    "disk_used_gb": 45.2,
    "disk_total_gb": 100.0,
    "containers_running": 15,
    "containers_total": 18
  },
  "applications": [
    {
      "name": "my-app",
      "cpu_percent": 15.2,
      "memory_mb": 256,
      "replicas": 3,
      "rps": 127.5
    }
  ],
  "network": {
    "requests_per_second": 342.1,
    "total_requests": 1587432,
    "error_rate_percent": 0.12,
    "avg_response_time_ms": 95
  }
}
```

## Configuration Management

### Get Configuration

Get current Orchestry configuration.

```http
GET /api/v1/config
```

**Response:**
```json
{
  "version": "1.0.0",
  "controller": {
    "host": "0.0.0.0",
    "port": 8000,
    "workers": 4
  },
  "database": {
    "host": "orchestry-postgres-primary",
    "port": 5432,
    "name": "orchestry",
    "pool_size": 10
  },
  "scaling": {
    "default_check_interval": 30,
    "default_cooldown": 180,
    "max_concurrent_scales": 3
  },
  "health": {
    "default_check_interval": 10,
    "default_timeout": 5,
    "default_failure_threshold": 3
  }
}
```

### Update Configuration

Update Orchestry configuration (requires restart).

```http
PUT /api/v1/config
```

**Request Body:**
```json
{
  "scaling": {
    "default_check_interval": 45,
    "default_cooldown": 300
  },
  "health": {
    "default_check_interval": 15
  }
}
```

## WebSocket Endpoints

### Real-time Logs

Stream application logs in real-time.

```javascript
const ws = new WebSocket('ws://localhost:8000/api/v1/apps/my-app/logs/stream');

ws.onmessage = function(event) {
  const logEntry = JSON.parse(event.data);
  console.log(`[${logEntry.timestamp}] ${logEntry.container}: ${logEntry.message}`);
};
```

### Real-time Metrics

Stream application metrics in real-time.

```javascript
const ws = new WebSocket('ws://localhost:8000/api/v1/apps/my-app/metrics/stream');

ws.onmessage = function(event) {
  const metrics = JSON.parse(event.data);
  console.log(`CPU: ${metrics.cpu_percent}%, Memory: ${metrics.memory_percent}%`);
};
```

### System Events

Stream system-wide events.

```javascript
const ws = new WebSocket('ws://localhost:8000/api/v1/events/stream');

ws.onmessage = function(event) {
  const event = JSON.parse(event.data);
  console.log(`[${event.type}] ${event.app_name}: ${event.message}`);
};
```

## Rate Limiting

API endpoints are rate limited to prevent abuse:

- **Per IP**: 1000 requests per hour
- **Per endpoint**: Varies by endpoint type
- **Burst limit**: 100 requests per minute

Rate limit headers are included in responses:

```http
X-RateLimit-Limit: 1000
X-RateLimit-Remaining: 999
X-RateLimit-Reset: 1642248000
```

## Error Codes

| Code | Description | HTTP Status |
|------|-------------|-------------|
| `APP_NOT_FOUND` | Application not found | 404 |
| `APP_ALREADY_EXISTS` | Application already registered | 409 |
| `INVALID_SPEC` | Invalid application specification | 400 |
| `SCALING_IN_PROGRESS` | Scaling operation in progress | 409 |
| `INSUFFICIENT_RESOURCES` | Not enough system resources | 503 |
| `DOCKER_ERROR` | Docker daemon error | 500 |
| `DATABASE_ERROR` | Database connection error | 500 |
| `VALIDATION_ERROR` | Request validation failed | 400 |
| `RATE_LIMIT_EXCEEDED` | Rate limit exceeded | 429 |

## Cluster Management

These endpoints are available when Orchestry is running in distributed cluster mode.

### Get Cluster Status

Get comprehensive cluster status and node information.

```http
GET /cluster/status
```

**Response:**
```json
{
  "node_id": "controller-1",
  "hostname": "controller-1.local",
  "state": "leader",
  "term": 5,
  "is_leader": true,
  "leader_id": "controller-1",
  "cluster_size": 3,
  "nodes": [
    {
      "node_id": "controller-1",
      "hostname": "controller-1.local",
      "state": "leader",
      "is_healthy": true,
      "last_heartbeat": 1642248600.123
    },
    {
      "node_id": "controller-2", 
      "hostname": "controller-2.local",
      "state": "follower",
      "is_healthy": true,
      "last_heartbeat": 1642248595.456
    },
    {
      "node_id": "controller-3",
      "hostname": "controller-3.local", 
      "state": "follower",
      "is_healthy": true,
      "last_heartbeat": 1642248598.789
    }
  ],
  "lease": {
    "leader_id": "controller-1",
    "term": 5,
    "acquired_at": 1642248500.0,
    "expires_at": 1642248630.0,
    "renewed_at": 1642248600.0,
    "hostname": "controller-1.local",
    "api_url": "http://controller-1.local:8001"
  }
}
```

### Get Current Leader

Get information about the current cluster leader.

```http
GET /cluster/leader
```

**Response:**
```json
{
  "leader_id": "controller-1",
  "hostname": "controller-1.local",
  "api_url": "http://controller-1.local:8001",
  "term": 5,
  "lease_expires_at": 1642248630.0
}
```

**Error Response (No leader elected):**
```json
{
  "error": "No leader elected",
  "code": "NO_LEADER",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### Cluster Health Check

Get cluster health status with leadership information.

```http
GET /cluster/health
```

**Response (Healthy cluster):**
```json
{
  "status": "healthy",
  "clustering": "enabled",
  "node_id": "controller-1",
  "state": "leader",
  "is_leader": true,
  "leader_id": "controller-1",
  "cluster_size": 3,
  "cluster_ready": true,
  "timestamp": 1642248600.123,
  "version": "1.0.0"
}
```

**Response (Single node mode):**
```json
{
  "status": "healthy",
  "clustering": "disabled",
  "timestamp": 1642248600.123,
  "version": "1.0.0"
}
```

**Response (Degraded cluster):**
```json
{
  "status": "degraded",
  "clustering": "enabled",
  "node_id": "controller-2",
  "state": "follower",
  "is_leader": false,
  "leader_id": null,
  "cluster_size": 2,
  "cluster_ready": false,
  "timestamp": 1642248600.123,
  "version": "1.0.0"
}
```

### Leader Redirection

When write operations are sent to a non-leader node, the API returns a redirect response:

```http
POST /api/v1/apps/register
```

**Response (From non-leader node):**
```json
HTTP/1.1 307 Temporary Redirect
Location: http://controller-1.local:8001/api/v1/apps/register

{
  "error": "Request must be sent to leader node: http://controller-1.local:8001",
  "code": "NOT_LEADER",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

**Response (No leader available):**
```json
HTTP/1.1 503 Service Unavailable

{
  "error": "No leader elected, cluster not ready",
  "code": "CLUSTER_NOT_READY", 
  "timestamp": "2024-01-15T10:30:00Z"
}
```

## SDKs and Libraries

### Python SDK

```python
import orchestry

client = orchestry.Client("http://localhost:8000")

# Register application
with open('app.yml') as f:
    spec = yaml.safe_load(f)
client.register_app(spec)

# Start application
client.start_app("my-app", replicas=3)

# Get status
status = client.get_app_status("my-app")
print(f"App is {status['status']} with {status['replicas']['current']} replicas")
```

### Node.js SDK

```javascript
const Orchestry = require('orchestry-client');

const client = new Orchestry('http://localhost:8000');

// Register application
const spec = require('./app.json');
await client.registerApp(spec);

// Start application
await client.startApp('my-app', { replicas: 3 });

// Get status
const status = await client.getAppStatus('my-app');
console.log(`App is ${status.status} with ${status.replicas.current} replicas`);
```

---

**Next Steps**: Learn about [Configuration](configuration.md) for advanced settings and environment setup.