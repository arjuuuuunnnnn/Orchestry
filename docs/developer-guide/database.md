# Database Schema

Complete documentation of AutoServe's database schema, data models, and persistence layer.

## Overview

AutoServe uses PostgreSQL as its primary datastore with an optional read replica for scalability. The database schema is designed for:

- **High Performance**: Optimized queries with proper indexing
- **Scalability**: Support for large numbers of applications and metrics
- **Consistency**: ACID transactions for critical operations
- **Auditability**: Complete event trail for all operations
- **Extensibility**: Schema designed for future enhancements

## Database Architecture

### Primary-Replica Setup

```
┌─────────────────────────┐    ┌─────────────────────────┐
│    Primary Database     │    │    Replica Database     │
│                         │    │                         │
│  • Read/Write          │◄──►│  • Read Only            │
│  • Real-time data      │    │  • Analytics queries    │
│  • Critical operations │    │  • Reporting            │
│  • Schema changes      │    │  • Backup source        │
└─────────────────────────┘    └─────────────────────────┘
```

### Connection Management

```python
class DatabaseManager:
    """Database connection and query management."""
    
    def __init__(self, config):
        self.primary_pool = None    # Read/write operations
        self.replica_pool = None    # Read-only operations
        self.config = config
        
    async def get_write_connection(self):
        """Get connection for write operations."""
        return await self.primary_pool.acquire()
        
    async def get_read_connection(self):
        """Get connection for read operations."""
        if self.replica_pool and self.config.get('prefer_replica'):
            return await self.replica_pool.acquire()
        return await self.primary_pool.acquire()
```

## Core Tables

### Applications Table

Stores application specifications and metadata.

```sql
CREATE TABLE applications (
    -- Primary identification
    name VARCHAR(253) PRIMARY KEY,              -- DNS-compatible app name
    
    -- Application specification
    spec JSONB NOT NULL,                        -- Complete app specification
    status VARCHAR(50) NOT NULL DEFAULT 'registered', -- Current status
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Scaling information
    replicas INTEGER DEFAULT 0,                 -- Current replica count
    desired_replicas INTEGER DEFAULT 0,         -- Desired replica count
    last_scaled_at TIMESTAMP WITH TIME ZONE,    -- Last scaling operation
    
    -- Configuration
    mode VARCHAR(20) DEFAULT 'auto',            -- Scaling mode (auto/manual)
    
    -- Constraints
    CONSTRAINT valid_status CHECK (status IN (
        'registered', 'starting', 'running', 'stopping', 'stopped', 'error', 'updating'
    )),
    CONSTRAINT valid_mode CHECK (mode IN ('auto', 'manual')),
    CONSTRAINT valid_replicas CHECK (replicas >= 0),
    CONSTRAINT valid_desired_replicas CHECK (desired_replicas >= 0)
);

-- Indexes for performance
CREATE INDEX idx_applications_status ON applications(status);
CREATE INDEX idx_applications_mode ON applications(mode);
CREATE INDEX idx_applications_updated_at ON applications(updated_at DESC);
CREATE INDEX idx_applications_spec_image ON applications USING GIN ((spec->'spec'->>'image'));
```

**Application Status Values:**

| Status | Description |
|--------|-------------|
| `registered` | Application spec stored, not yet started |
| `starting` | Containers being created |
| `running` | Application running normally |
| `stopping` | Graceful shutdown in progress |
| `stopped` | Application stopped |
| `error` | Error state, manual intervention needed |
| `updating` | Configuration or image update in progress |

### Instances Table

Tracks individual container instances for each application.

```sql
CREATE TABLE instances (
    -- Primary key
    id SERIAL PRIMARY KEY,
    
    -- Application relationship
    app_name VARCHAR(253) NOT NULL REFERENCES applications(name) ON DELETE CASCADE,
    
    -- Container identification
    container_id VARCHAR(128) UNIQUE NOT NULL,  -- Docker container ID
    container_name VARCHAR(253) NOT NULL,       -- Human-readable container name
    replica_index INTEGER NOT NULL,             -- Replica number (0, 1, 2, ...)
    
    -- Network configuration
    ip INET NOT NULL,                           -- Container IP address
    port INTEGER NOT NULL,                      -- Primary application port
    
    -- Status information
    status VARCHAR(50) NOT NULL DEFAULT 'starting',
    health_status VARCHAR(20) DEFAULT 'unknown', -- Health check status
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    started_at TIMESTAMP WITH TIME ZONE,        -- When container started
    last_health_check TIMESTAMP WITH TIME ZONE,
    
    -- Failure tracking
    failure_count INTEGER DEFAULT 0,
    consecutive_failures INTEGER DEFAULT 0,
    last_failure_at TIMESTAMP WITH TIME ZONE,
    
    -- Resource usage (latest values)
    cpu_percent REAL DEFAULT 0,
    memory_percent REAL DEFAULT 0,
    memory_usage_bytes BIGINT DEFAULT 0,
    
    -- Constraints
    CONSTRAINT valid_status CHECK (status IN (
        'starting', 'running', 'stopping', 'stopped', 'error', 'draining'
    )),
    CONSTRAINT valid_health_status CHECK (health_status IN (
        'unknown', 'healthy', 'unhealthy', 'starting'
    )),
    CONSTRAINT valid_replica_index CHECK (replica_index >= 0),
    CONSTRAINT valid_port CHECK (port > 0 AND port <= 65535),
    CONSTRAINT valid_failure_count CHECK (failure_count >= 0),
    CONSTRAINT valid_cpu_percent CHECK (cpu_percent >= 0),
    CONSTRAINT valid_memory_percent CHECK (memory_percent >= 0 AND memory_percent <= 100),
    
    -- Unique constraint for app + replica
    UNIQUE(app_name, replica_index)
);

-- Indexes for performance
CREATE INDEX idx_instances_app_name ON instances(app_name);
CREATE INDEX idx_instances_status ON instances(status);
CREATE INDEX idx_instances_health_status ON instances(health_status);
CREATE INDEX idx_instances_container_id ON instances(container_id);
CREATE INDEX idx_instances_updated_at ON instances(updated_at DESC);
CREATE INDEX idx_instances_app_status ON instances(app_name, status);
CREATE INDEX idx_instances_health_check ON instances(last_health_check DESC);
```

**Instance Status Values:**

| Status | Description |
|--------|-------------|
| `starting` | Container is being created/started |
| `running` | Container is running normally |
| `stopping` | Container is being gracefully stopped |
| `stopped` | Container has stopped |
| `error` | Container in error state |
| `draining` | Container marked for removal, not receiving new traffic |

### Events Table

Comprehensive audit trail of all system events.

```sql
CREATE TABLE events (
    -- Primary key
    id SERIAL PRIMARY KEY,
    
    -- Event identification
    event_type VARCHAR(50) NOT NULL,            -- Type of event
    event_category VARCHAR(30) NOT NULL DEFAULT 'application', -- Event category
    
    -- Associated resources
    app_name VARCHAR(253) REFERENCES applications(name) ON DELETE SET NULL,
    container_id VARCHAR(128),                  -- Optional container reference
    
    -- Event details
    message TEXT NOT NULL,                      -- Human-readable message
    details JSONB,                              -- Structured event data
    severity VARCHAR(20) DEFAULT 'info',       -- Event severity level
    
    -- Timestamps
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Source information
    source VARCHAR(50) DEFAULT 'controller',    -- Component that generated event
    node_id VARCHAR(100),                       -- Cluster node ID (if applicable)
    
    -- Constraints
    CONSTRAINT valid_event_type CHECK (event_type IN (
        'registration', 'scaling', 'health', 'config', 'deployment', 
        'error', 'warning', 'network', 'resource', 'security'
    )),
    CONSTRAINT valid_event_category CHECK (event_category IN (
        'application', 'system', 'cluster', 'security', 'performance'
    )),
    CONSTRAINT valid_severity CHECK (severity IN (
        'debug', 'info', 'warning', 'error', 'critical'
    ))
);

-- Indexes for efficient querying
CREATE INDEX idx_events_app_name_timestamp ON events(app_name, timestamp DESC);
CREATE INDEX idx_events_type_timestamp ON events(event_type, timestamp DESC);
CREATE INDEX idx_events_timestamp ON events(timestamp DESC);
CREATE INDEX idx_events_severity ON events(severity, timestamp DESC);
CREATE INDEX idx_events_category ON events(event_category, timestamp DESC);
CREATE INDEX idx_events_container ON events(container_id, timestamp DESC);

-- Partial index for recent events (performance optimization)
CREATE INDEX idx_events_recent ON events(timestamp DESC) 
WHERE timestamp > NOW() - INTERVAL '7 days';
```

**Event Types:**

| Type | Description | Example Details |
|------|-------------|-----------------|
| `registration` | App registered/updated | `{"image": "nginx:alpine", "replicas": 3}` |
| `scaling` | Scaling operation | `{"from": 2, "to": 5, "reason": "high_cpu"}` |
| `health` | Health status change | `{"status": "unhealthy", "failures": 3}` |
| `config` | Configuration change | `{"field": "replicas", "old": 2, "new": 3}` |
| `deployment` | Deployment operation | `{"action": "deploy", "version": "v1.2.0"}` |
| `error` | Error occurred | `{"error": "ImagePullBackOff", "code": "E001"}` |

### Metrics Table (Time Series)

Historical performance and resource metrics.

```sql
CREATE TABLE metrics (
    -- Primary key
    id SERIAL PRIMARY KEY,
    
    -- Metric identification
    app_name VARCHAR(253) NOT NULL REFERENCES applications(name) ON DELETE CASCADE,
    metric_type VARCHAR(50) NOT NULL,           -- Type of metric
    
    -- Time series data
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    value REAL NOT NULL,                        -- Metric value
    
    -- Additional metadata
    labels JSONB,                               -- Key-value labels
    unit VARCHAR(20),                           -- Metric unit (%, bytes, ms, etc.)
    
    -- Aggregation level
    aggregation_level VARCHAR(20) DEFAULT 'instance', -- instance, app, system
    
    -- Constraints
    CONSTRAINT valid_metric_type CHECK (metric_type IN (
        'cpu_percent', 'memory_percent', 'memory_bytes', 'rps', 
        'latency_p50', 'latency_p95', 'latency_p99', 'active_connections',
        'error_rate', 'response_time', 'queue_length', 'disk_usage'
    )),
    CONSTRAINT valid_aggregation_level CHECK (aggregation_level IN (
        'instance', 'app', 'system'
    ))
);

-- Time series indexes (critical for performance)
CREATE INDEX idx_metrics_app_timestamp ON metrics(app_name, timestamp DESC);
CREATE INDEX idx_metrics_type_timestamp ON metrics(metric_type, timestamp DESC);
CREATE INDEX idx_metrics_timestamp ON metrics(timestamp DESC);
CREATE INDEX idx_metrics_app_type_time ON metrics(app_name, metric_type, timestamp DESC);

-- Partitioning for large datasets (optional)
-- CREATE TABLE metrics_2024_01 PARTITION OF metrics
-- FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');
```

### Scaling Policies Table

Stores scaling policies and configurations.

```sql
CREATE TABLE scaling_policies (
    -- Primary key
    app_name VARCHAR(253) PRIMARY KEY REFERENCES applications(name) ON DELETE CASCADE,
    
    -- Basic scaling parameters
    min_replicas INTEGER NOT NULL DEFAULT 1,
    max_replicas INTEGER NOT NULL DEFAULT 5,
    
    -- Performance targets
    target_rps_per_replica INTEGER DEFAULT 50,
    max_p95_latency_ms INTEGER DEFAULT 250,
    max_cpu_percent REAL DEFAULT 70.0,
    max_memory_percent REAL DEFAULT 75.0,
    max_connections_per_replica INTEGER DEFAULT 100,
    
    -- Scaling behavior
    scale_out_threshold_pct INTEGER DEFAULT 80,
    scale_in_threshold_pct INTEGER DEFAULT 30,
    cooldown_seconds INTEGER DEFAULT 180,
    evaluation_window_seconds INTEGER DEFAULT 60,
    
    -- Advanced settings
    max_scale_out_step INTEGER DEFAULT 0,       -- 0 means no limit
    max_scale_in_step INTEGER DEFAULT 1,
    stabilization_window_seconds INTEGER DEFAULT 300,
    
    -- Metric weights (for future use)
    cpu_weight REAL DEFAULT 1.0,
    memory_weight REAL DEFAULT 1.0,
    rps_weight REAL DEFAULT 1.0,
    latency_weight REAL DEFAULT 1.5,
    connection_weight REAL DEFAULT 0.8,
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT valid_replica_bounds CHECK (min_replicas <= max_replicas),
    CONSTRAINT valid_min_replicas CHECK (min_replicas >= 0),
    CONSTRAINT valid_max_replicas CHECK (max_replicas >= 1),
    CONSTRAINT valid_thresholds CHECK (scale_in_threshold_pct < scale_out_threshold_pct),
    CONSTRAINT valid_percentages CHECK (
        scale_out_threshold_pct BETWEEN 1 AND 100 AND
        scale_in_threshold_pct BETWEEN 1 AND 100
    ),
    CONSTRAINT valid_weights CHECK (
        cpu_weight >= 0 AND memory_weight >= 0 AND rps_weight >= 0 AND
        latency_weight >= 0 AND connection_weight >= 0
    )
);

-- Index for policy lookups
CREATE INDEX idx_scaling_policies_updated_at ON scaling_policies(updated_at DESC);
```

### Health Checks Table

Configuration and status of health checks.

```sql
CREATE TABLE health_checks (
    -- Primary key
    id SERIAL PRIMARY KEY,
    
    -- Application relationship
    app_name VARCHAR(253) NOT NULL REFERENCES applications(name) ON DELETE CASCADE,
    
    -- Health check configuration
    protocol VARCHAR(10) NOT NULL DEFAULT 'HTTP',
    path VARCHAR(500),                          -- HTTP path
    port INTEGER NOT NULL,
    method VARCHAR(10) DEFAULT 'GET',           -- HTTP method
    headers JSONB,                              -- HTTP headers
    body TEXT,                                  -- Request body
    expected_status_codes INTEGER[] DEFAULT ARRAY[200],
    
    -- Timing configuration
    initial_delay_seconds INTEGER DEFAULT 30,
    period_seconds INTEGER DEFAULT 30,
    timeout_seconds INTEGER DEFAULT 5,
    failure_threshold INTEGER DEFAULT 3,
    success_threshold INTEGER DEFAULT 1,
    
    -- Status
    enabled BOOLEAN DEFAULT true,
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT valid_protocol CHECK (protocol IN ('HTTP', 'TCP')),
    CONSTRAINT valid_method CHECK (method IN ('GET', 'POST', 'PUT', 'HEAD')),
    CONSTRAINT valid_port CHECK (port > 0 AND port <= 65535),
    CONSTRAINT valid_timings CHECK (
        initial_delay_seconds >= 0 AND
        period_seconds > 0 AND
        timeout_seconds > 0 AND
        failure_threshold > 0 AND
        success_threshold > 0
    ),
    
    -- Unique health check per app
    UNIQUE(app_name)
);

-- Index for health check lookups
CREATE INDEX idx_health_checks_app_name ON health_checks(app_name);
CREATE INDEX idx_health_checks_enabled ON health_checks(enabled);
```

## Data Models (Python)

### Application Record

```python
@dataclass
class AppRecord:
    """Application record data model."""
    name: str
    spec: Dict[str, Any]
    status: str
    created_at: float
    updated_at: float
    replicas: int = 0
    desired_replicas: int = 0
    last_scaled_at: Optional[float] = None
    mode: str = 'auto'
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'name': self.name,
            'spec': self.spec,
            'status': self.status,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'replicas': self.replicas,
            'desired_replicas': self.desired_replicas,
            'last_scaled_at': self.last_scaled_at,
            'mode': self.mode
        }
    
    @classmethod
    def from_db_row(cls, row) -> 'AppRecord':
        """Create from database row."""
        return cls(
            name=row['name'],
            spec=json.loads(row['spec']) if isinstance(row['spec'], str) else row['spec'],
            status=row['status'],
            created_at=row['created_at'].timestamp(),
            updated_at=row['updated_at'].timestamp(),
            replicas=row['replicas'],
            desired_replicas=row.get('desired_replicas', 0),
            last_scaled_at=row['last_scaled_at'].timestamp() if row['last_scaled_at'] else None,
            mode=row['mode']
        )
```

### Instance Record

```python
@dataclass
class InstanceRecord:
    """Container instance record data model."""
    id: Optional[int]
    app_name: str
    container_id: str
    container_name: str
    replica_index: int
    ip: str
    port: int
    status: str
    health_status: str
    created_at: float
    updated_at: float
    started_at: Optional[float] = None
    last_health_check: Optional[float] = None
    failure_count: int = 0
    consecutive_failures: int = 0
    last_failure_at: Optional[float] = None
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    memory_usage_bytes: int = 0
    
    def is_healthy(self) -> bool:
        """Check if instance is healthy."""
        return (self.status == 'running' and 
                self.health_status == 'healthy' and
                self.consecutive_failures < 3)
    
    def is_ready_for_traffic(self) -> bool:
        """Check if instance can receive traffic."""
        return (self.status == 'running' and 
                self.health_status in ['healthy', 'starting'] and
                self.consecutive_failures < 5)
```

### Event Record

```python
@dataclass
class EventRecord:
    """System event record data model."""
    id: Optional[int]
    event_type: str
    event_category: str
    app_name: Optional[str]
    container_id: Optional[str]
    message: str
    details: Optional[Dict[str, Any]]
    severity: str
    timestamp: float
    source: str = 'controller'
    node_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            'id': self.id,
            'event_type': self.event_type,
            'event_category': self.event_category,
            'app_name': self.app_name,
            'container_id': self.container_id,
            'message': self.message,
            'details': self.details,
            'severity': self.severity,
            'timestamp': self.timestamp,
            'source': self.source,
            'node_id': self.node_id
        }
```

## Database Operations

### Connection Management

```python
class DatabasePool:
    """Database connection pool manager."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.primary_pool = None
        self.replica_pool = None
        self._locks = {
            'primary': asyncio.Lock(),
            'replica': asyncio.Lock()
        }
    
    async def initialize_primary(self):
        """Initialize primary database connection pool."""
        async with self._locks['primary']:
            if self.primary_pool is None:
                self.primary_pool = await asyncpg.create_pool(
                    host=self.config['primary']['host'],
                    port=self.config['primary']['port'],
                    user=self.config['primary']['user'],
                    password=self.config['primary']['password'],
                    database=self.config['primary']['database'],
                    min_size=self.config.get('pool_min_size', 5),
                    max_size=self.config.get('pool_max_size', 20),
                    command_timeout=self.config.get('command_timeout', 30),
                    server_settings={
                        'application_name': 'autoserve_controller',
                        'jit': 'off'  # Disable JIT for better predictability
                    }
                )
    
    async def initialize_replica(self):
        """Initialize replica database connection pool."""
        if not self.config.get('replica', {}).get('enabled', False):
            return
            
        async with self._locks['replica']:
            if self.replica_pool is None:
                try:
                    self.replica_pool = await asyncpg.create_pool(
                        host=self.config['replica']['host'],
                        port=self.config['replica']['port'],
                        user=self.config['replica']['user'],
                        password=self.config['replica']['password'],
                        database=self.config['replica']['database'],
                        min_size=self.config.get('pool_min_size', 3),
                        max_size=self.config.get('pool_max_size', 10),
                        command_timeout=self.config.get('command_timeout', 30),
                        server_settings={
                            'application_name': 'autoserve_controller_read',
                            'default_transaction_isolation': 'repeatable_read'
                        }
                    )
                except Exception as e:
                    logger.warning(f"Failed to initialize replica pool: {e}")
```

### Query Patterns

```python
class ApplicationQueries:
    """Optimized queries for application operations."""
    
    @staticmethod
    async def get_app_with_instances(conn, app_name: str) -> Optional[Dict[str, Any]]:
        """Get application with all instances in a single query."""
        query = """
        SELECT 
            a.*,
            COALESCE(
                json_agg(
                    json_build_object(
                        'id', i.id,
                        'container_id', i.container_id,
                        'container_name', i.container_name,
                        'replica_index', i.replica_index,
                        'ip', i.ip,
                        'port', i.port,
                        'status', i.status,
                        'health_status', i.health_status,
                        'cpu_percent', i.cpu_percent,
                        'memory_percent', i.memory_percent,
                        'failure_count', i.failure_count,
                        'last_health_check', EXTRACT(EPOCH FROM i.last_health_check)
                    ) ORDER BY i.replica_index
                ) FILTER (WHERE i.id IS NOT NULL),
                '[]'::json
            ) as instances
        FROM applications a
        LEFT JOIN instances i ON a.name = i.app_name AND i.status != 'stopped'
        WHERE a.name = $1
        GROUP BY a.name
        """
        
        row = await conn.fetchrow(query, app_name)
        if not row:
            return None
            
        return {
            'app': AppRecord.from_db_row(row),
            'instances': [InstanceRecord(**instance) for instance in row['instances']]
        }
    
    @staticmethod
    async def get_apps_summary(conn, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get summary of all applications with instance counts."""
        conditions = []
        params = []
        
        if status_filter:
            conditions.append("a.status = $1")
            params.append(status_filter)
        
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        
        query = f"""
        SELECT 
            a.name,
            a.status,
            a.replicas,
            a.desired_replicas,
            a.mode,
            a.created_at,
            a.updated_at,
            a.last_scaled_at,
            COUNT(i.id) FILTER (WHERE i.status = 'running') as running_instances,
            COUNT(i.id) FILTER (WHERE i.health_status = 'healthy') as healthy_instances,
            AVG(i.cpu_percent) FILTER (WHERE i.status = 'running') as avg_cpu_percent,
            AVG(i.memory_percent) FILTER (WHERE i.status = 'running') as avg_memory_percent
        FROM applications a
        LEFT JOIN instances i ON a.name = i.app_name
        {where_clause}
        GROUP BY a.name, a.status, a.replicas, a.desired_replicas, a.mode, 
                 a.created_at, a.updated_at, a.last_scaled_at
        ORDER BY a.name
        """
        
        rows = await conn.fetch(query, *params)
        return [dict(row) for row in rows]
```

### Metrics Aggregation

```python
class MetricsQueries:
    """Optimized queries for metrics operations."""
    
    @staticmethod
    async def get_app_metrics_window(conn, app_name: str, window_minutes: int = 5) -> Dict[str, Any]:
        """Get aggregated metrics for an application over a time window."""
        query = """
        SELECT 
            metric_type,
            AVG(value) as avg_value,
            MIN(value) as min_value,
            MAX(value) as max_value,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY value) as p50_value,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY value) as p95_value,
            COUNT(*) as data_points
        FROM metrics
        WHERE app_name = $1 
          AND timestamp >= NOW() - INTERVAL '%s minutes'
          AND metric_type IN ('cpu_percent', 'memory_percent', 'rps', 'latency_p95', 'active_connections')
        GROUP BY metric_type
        """ % window_minutes
        
        rows = await conn.fetch(query, app_name)
        
        metrics = {}
        for row in rows:
            metrics[row['metric_type']] = {
                'avg': float(row['avg_value']) if row['avg_value'] else 0,
                'min': float(row['min_value']) if row['min_value'] else 0,
                'max': float(row['max_value']) if row['max_value'] else 0,
                'p50': float(row['p50_value']) if row['p50_value'] else 0,
                'p95': float(row['p95_value']) if row['p95_value'] else 0,
                'data_points': row['data_points']
            }
        
        return metrics
    
    @staticmethod
    async def cleanup_old_metrics(conn, retention_hours: int = 168):
        """Clean up metrics older than retention period."""
        query = """
        DELETE FROM metrics 
        WHERE timestamp < NOW() - INTERVAL '%s hours'
        """ % retention_hours
        
        result = await conn.execute(query)
        deleted_count = int(result.split()[1])
        return deleted_count
```

## Performance Optimization

### Indexing Strategy

```sql
-- Composite indexes for common query patterns
CREATE INDEX idx_instances_app_status_health ON instances(app_name, status, health_status);
CREATE INDEX idx_events_app_type_severity ON events(app_name, event_type, severity, timestamp DESC);
CREATE INDEX idx_metrics_app_type_recent ON metrics(app_name, metric_type, timestamp DESC)
WHERE timestamp > NOW() - INTERVAL '24 hours';

-- Partial indexes for active data
CREATE INDEX idx_applications_active ON applications(name, status, updated_at)
WHERE status IN ('running', 'starting', 'updating');

CREATE INDEX idx_instances_active ON instances(app_name, status, health_status, updated_at)
WHERE status IN ('running', 'starting');
```

### Query Optimization

```python
class QueryOptimizer:
    """Database query optimization utilities."""
    
    @staticmethod
    async def explain_query(conn, query: str, params: List[Any] = None) -> str:
        """Get query execution plan."""
        explain_query = f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {query}"
        result = await conn.fetch(explain_query, *(params or []))
        return json.dumps(result[0]['QUERY PLAN'], indent=2)
    
    @staticmethod
    async def get_slow_queries(conn, min_duration_ms: int = 1000) -> List[Dict[str, Any]]:
        """Get slow queries from pg_stat_statements."""
        query = """
        SELECT 
            query,
            calls,
            total_time,
            mean_time,
            stddev_time,
            rows,
            100.0 * shared_blks_hit / nullif(shared_blks_hit + shared_blks_read, 0) AS hit_percent
        FROM pg_stat_statements
        WHERE mean_time > $1
        ORDER BY mean_time DESC
        LIMIT 20
        """
        
        rows = await conn.fetch(query, min_duration_ms)
        return [dict(row) for row in rows]
```

### Connection Pool Tuning

```python
# Optimal pool configuration
POOL_CONFIG = {
    'primary': {
        'min_size': 5,          # Always keep 5 connections open
        'max_size': 20,         # Maximum 20 connections
        'command_timeout': 30,   # 30 second query timeout
        'max_queries': 50000,    # Recycle connections after 50k queries
        'max_inactive_time': 300 # Close inactive connections after 5 minutes
    },
    'replica': {
        'min_size': 3,          # Fewer connections for read replica
        'max_size': 10,         # Lower maximum for read workload
        'command_timeout': 60,   # Longer timeout for analytical queries
        'max_queries': 100000,   # Recycle less frequently
        'max_inactive_time': 600 # Keep connections longer for batch operations
    }
}
```

## Data Retention and Archival

### Automatic Cleanup

```sql
-- Function to clean up old data
CREATE OR REPLACE FUNCTION cleanup_old_data()
RETURNS TABLE(table_name TEXT, deleted_count INTEGER) AS $$
BEGIN
    -- Clean up old events (keep 30 days)
    DELETE FROM events WHERE timestamp < NOW() - INTERVAL '30 days';
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    table_name := 'events';
    RETURN NEXT;
    
    -- Clean up old metrics (keep 7 days for instance level, 30 days for app level)
    DELETE FROM metrics 
    WHERE timestamp < NOW() - INTERVAL '7 days' 
      AND aggregation_level = 'instance';
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    table_name := 'metrics (instance)';
    RETURN NEXT;
    
    DELETE FROM metrics 
    WHERE timestamp < NOW() - INTERVAL '30 days' 
      AND aggregation_level = 'app';
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    table_name := 'metrics (app)';
    RETURN NEXT;
    
    -- Clean up stopped instances (keep 7 days)
    DELETE FROM instances 
    WHERE status = 'stopped' 
      AND updated_at < NOW() - INTERVAL '7 days';
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    table_name := 'instances (stopped)';
    RETURN NEXT;
END;
$$ LANGUAGE plpgsql;

-- Schedule cleanup (requires pg_cron extension)
SELECT cron.schedule('cleanup-old-data', '0 2 * * *', 'SELECT cleanup_old_data();');
```

### Archival Strategy

```python
class DataArchival:
    """Data archival and retention management."""
    
    async def archive_old_metrics(self, cutoff_date: datetime, archive_table: str):
        """Archive old metrics to separate table."""
        async with self.get_write_connection() as conn:
            # Create archive table if it doesn't exist
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {archive_table} 
                (LIKE metrics INCLUDING ALL)
            """)
            
            # Move old data to archive
            await conn.execute(f"""
                WITH moved_data AS (
                    DELETE FROM metrics 
                    WHERE timestamp < $1 
                    RETURNING *
                )
                INSERT INTO {archive_table} 
                SELECT * FROM moved_data
            """, cutoff_date)
    
    async def compress_old_events(self, days_old: int = 90):
        """Compress old events to reduce storage."""
        async with self.get_write_connection() as conn:
            # Aggregate old events by hour
            await conn.execute("""
                INSERT INTO events_compressed (
                    hour_bucket, app_name, event_type, event_count, 
                    severity_counts, sample_messages
                )
                SELECT 
                    date_trunc('hour', timestamp) as hour_bucket,
                    app_name,
                    event_type,
                    COUNT(*) as event_count,
                    json_object_agg(severity, severity_count) as severity_counts,
                    array_agg(DISTINCT message ORDER BY timestamp DESC LIMIT 5) as sample_messages
                FROM events
                CROSS JOIN LATERAL (
                    SELECT severity, COUNT(*) as severity_count
                    FROM events e2
                    WHERE e2.timestamp = events.timestamp
                      AND e2.app_name = events.app_name
                      AND e2.event_type = events.event_type
                    GROUP BY severity
                ) severity_agg
                WHERE timestamp < NOW() - INTERVAL '%s days'
                GROUP BY date_trunc('hour', timestamp), app_name, event_type
            """ % days_old)
            
            # Delete original events after compression
            result = await conn.execute(
                "DELETE FROM events WHERE timestamp < NOW() - INTERVAL '%s days'" % days_old
            )
            return int(result.split()[1])
```

---

**Next Steps**: Learn about [Load Balancing](load-balancing.md) and Nginx integration.