# Leader Election and Distributed Controller

Orchestry implements a distributed controller architecture with leader election to eliminate single points of failure and provide high availability for the control plane.

## Overview

The distributed controller system uses a 3-node cluster architecture with PostgreSQL-based leader election to ensure that only one controller node actively manages applications at any given time, while maintaining seamless failover capabilities.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           External Traffic                                  │
└─────────────────────────┬───────────────────────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────────────────────┐
│                  Nginx Load Balancer (Port 8000)                            │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  Upstream Configuration (Dynamic Leader Routing)                    │    │
│  │  • Write Operations → Leader Only                                   │    │
│  │  • Read Operations → All Healthy Nodes                              │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────┬───────────────────────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────────────────────┐
│                    Controller Cluster                                       │
│                                                                             │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐                │
│  │ Controller-1    │ │ Controller-2    │ │ Controller-3    │                │
│  │   (Leader)      │ │  (Follower)     │ │  (Follower)     │                │
│  │   Port 8001     │ │   Port 8002     │ │   Port 8003     │                │
│  └─────────────────┘ └─────────────────┘ └─────────────────┘                │
│           │                  │                      │                       │
│           └──────────────────┼──────────────────────┘                       │
│                              │                                              │
└──────────────────────────────┼──────────────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────────────┐
│                    PostgreSQL HA Cluster                                    │
│  ┌─────────────────┐                        ┌─────────────────┐             │
│  │    Primary      │◄──── Replication  ────►│     Replica     │             │
│  │   (Read/Write)  │                        │   (Read Only)   │             │
│  │  Leader Election│                        │   Coordination  │             │
│  │   Coordination  │                        │      Data       │             │
│  └─────────────────┘                        └─────────────────┘             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Leader Election Algorithm

Orchestry implements a simplified Raft-like consensus algorithm using PostgreSQL as the coordination backend. This approach leverages the database's ACID properties to ensure consistent leader election.

### Core Concepts

#### 1. Node States

Each controller node can be in one of four states:

```python
class NodeState(Enum):
    FOLLOWER = "follower"      # Default state, follows leader
    CANDIDATE = "candidate"    # Attempting to become leader
    LEADER = "leader"         # Actively managing applications
    STOPPED = "stopped"       # Node is shutting down
```

#### 2. Leadership Lease

The leader election uses a time-based lease system stored in PostgreSQL:

```python
@dataclass
class LeaderLease:
    leader_id: str          # Unique node identifier
    term: int              # Election term number
    acquired_at: float     # Timestamp when lease was acquired
    expires_at: float      # Timestamp when lease expires
    renewed_at: float      # Last renewal timestamp
    hostname: str          # Leader's hostname
    api_url: str          # Leader's API endpoint
```

#### 3. Database Schema

```sql
-- Cluster nodes table
CREATE TABLE cluster_nodes (
    node_id VARCHAR(255) PRIMARY KEY,
    hostname VARCHAR(255) NOT NULL,
    port INTEGER NOT NULL,
    api_url VARCHAR(512) NOT NULL,
    state VARCHAR(50) NOT NULL,
    term INTEGER NOT NULL DEFAULT 0,
    last_heartbeat TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_healthy BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Leader lease table (single row)
CREATE TABLE leader_lease (
    id INTEGER PRIMARY KEY DEFAULT 1,
    leader_id VARCHAR(255) NOT NULL,
    term INTEGER NOT NULL,
    acquired_at TIMESTAMP NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    renewed_at TIMESTAMP NOT NULL,
    hostname VARCHAR(255) NOT NULL,
    api_url VARCHAR(512) NOT NULL,
    CONSTRAINT single_lease CHECK (id = 1)
);

-- Cluster events log
CREATE TABLE cluster_events (
    id SERIAL PRIMARY KEY,
    node_id VARCHAR(255) NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    event_data JSONB,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

## Leader Election Process

### 1. Node Startup and Registration

When a controller node starts up:

```python
def start(self):
    """Start the distributed controller cluster"""
    if self._running:
        return
        
    logger.info(f"🚀 Starting distributed controller node {self.node_id}")
    
    # Initialize database tables
    self._init_cluster_tables()
    
    # Register this node
    self._register_node()
    
    # Start background coordination tasks
    self._start_background_tasks()
    
    self._running = True
    logger.info(f"✅ Distributed controller node {self.node_id} started")
```

### 2. Election Triggers

Elections are triggered when:
- No valid leader exists (lease expired)
- Node startup (check for existing leader)
- Leader failure detection
- Manual leadership release

```python
def _should_start_election(self) -> bool:
    """Check if we should start a leader election"""
    try:
        # Check if there's a current valid leader
        current_lease = self._get_current_lease()
        if current_lease and current_lease.expires_at > time.time():
            # Valid leader exists
            if current_lease.leader_id != self.leader_id:
                self.leader_id = current_lease.leader_id
                logger.info(f"👑 Acknowledged leader: {self.leader_id}")
            return False
            
        # No valid leader - check if we should start election
        if self.state == NodeState.FOLLOWER:
            logger.info("🗳️  No valid leader found, considering election...")
            return True
            
    except Exception as e:
        logger.error(f"❌ Error checking election conditions: {e}")
        
    return False
```

### 3. Lease Acquisition

The core of leader election is atomic lease acquisition:

```python
def _try_acquire_leadership(self) -> bool:
    """Try to acquire leadership lease atomically"""
    try:
        with self._get_db_connection() as conn:
            with conn.cursor() as cursor:
                # Try to acquire or update lease atomically
                cursor.execute("""
                    INSERT INTO leader_lease 
                    (id, leader_id, term, acquired_at, expires_at, renewed_at, hostname, api_url)
                    VALUES (1, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP + INTERVAL '%s seconds', CURRENT_TIMESTAMP, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        leader_id = EXCLUDED.leader_id,
                        term = EXCLUDED.term,
                        acquired_at = CURRENT_TIMESTAMP,
                        expires_at = CURRENT_TIMESTAMP + INTERVAL '%s seconds',
                        renewed_at = CURRENT_TIMESTAMP,
                        hostname = EXCLUDED.hostname,
                        api_url = EXCLUDED.api_url
                    WHERE leader_lease.expires_at <= CURRENT_TIMESTAMP 
                       OR leader_lease.term < EXCLUDED.term
                """, (
                    self.node_id,
                    self.current_term,
                    self.lease_ttl,
                    self.hostname,
                    self.api_url,
                    self.lease_ttl
                ))
                
                # Check if we actually acquired the lease
                if cursor.rowcount > 0:
                    conn.commit()
                    logger.info(f"✅ Acquired leadership lease for term {self.current_term}")
                    return True
                else:
                    conn.rollback()
                    return False
                    
    except Exception as e:
        logger.error(f"❌ Failed to acquire leadership lease: {e}")
        return False
```

### 4. Leadership Maintenance

Once elected, the leader must continuously renew its lease:

```python
def _renew_leadership_lease(self):
    """Renew leadership lease to maintain leadership"""
    if not self.is_leader:
        return
        
    try:
        with self._get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE leader_lease 
                    SET expires_at = CURRENT_TIMESTAMP + INTERVAL '%s seconds',
                        renewed_at = CURRENT_TIMESTAMP
                    WHERE leader_id = %s AND term = %s
                """, (self.lease_ttl, self.node_id, self.current_term))
                
                if cursor.rowcount == 0:
                    # We lost the lease somehow
                    logger.warning("⚠️  Lost leadership lease during renewal")
                    conn.rollback()
                    self._lose_leadership()
                else:
                    conn.commit()
                    
    except Exception as e:
        logger.error(f"❌ Failed to renew leadership lease: {e}")
        self._lose_leadership()
```

## Background Processes

The distributed controller runs three main background processes:

### 1. Heartbeat Loop

Maintains node presence and leader lease renewal:

```python
def _heartbeat_loop(self):
    """Background heartbeat to maintain node presence"""
    logger.info("💓 Starting heartbeat loop...")
    
    while self._running:
        try:
            self._send_heartbeat()
            
            # If we're the leader, renew our lease
            if self.is_leader:
                self._renew_leadership_lease()
                
        except Exception as e:
            logger.error(f"❌ Heartbeat error: {e}")
            
        time.sleep(self.heartbeat_interval)  # Default: 10 seconds
```

### 2. Election Loop

Monitors leader health and triggers elections:

```python
def _election_loop(self):
    """Background election monitoring and leadership checks"""
    logger.info("🗳️  Starting election monitoring loop...")
    
    while self._running:
        try:
            if not self.is_leader:
                # Check if we need to start an election
                if self._should_start_election():
                    self._start_leader_election()
                    
            # Check leader health and lease validity
            self._check_leader_health()
            
        except Exception as e:
            logger.error(f"❌ Election loop error: {e}")
            
        time.sleep(5)  # Check every 5 seconds
```

### 3. Cluster Monitoring Loop

Manages cluster membership and cleanup:

```python
def _cluster_monitor_loop(self):
    """Monitor cluster membership and health"""
    logger.info("🔍 Starting cluster monitoring loop...")
    
    while self._running:
        try:
            self._update_cluster_membership()
            self._cleanup_stale_nodes()
            
        except Exception as e:
            logger.error(f"❌ Cluster monitoring error: {e}")
            
        time.sleep(15)  # Check every 15 seconds
```

## API Integration

The leader election system integrates with the REST API through decorators and middleware:

### Leader-Only Operations

Critical write operations are restricted to the leader:

```python
def leader_required(f):
    """Decorator to ensure only the leader can execute certain operations"""
    @wraps(f)
    async def decorated_function(*args, **kwargs):
        if cluster_controller and not cluster_controller.is_leader:
            leader_info = cluster_controller.get_leader_info()
            if leader_info:
                raise HTTPException(
                    status_code=307, 
                    detail=f"Request must be sent to leader node: {leader_info['api_url']}",
                    headers={"Location": leader_info['api_url']}
                )
            else:
                raise HTTPException(
                    status_code=503, 
                    detail="No leader elected, cluster not ready"
                )
        return await f(*args, **kwargs)
    return decorated_function

# Usage
@app.post("/apps")
@leader_required
async def register_app(app_spec: AppSpec):
    """Register a new application (leader only)"""
    return await app_manager.register_app(app_spec.dict())
```

### Cluster Status Endpoints

```python
@app.get("/cluster/status")
async def get_cluster_status():
    """Get comprehensive cluster status"""
    if not cluster_controller:
        raise HTTPException(status_code=503, detail="Clustering not enabled")
        
    return cluster_controller.get_cluster_status()

@app.get("/cluster/leader")
async def get_cluster_leader():
    """Get current cluster leader information"""
    if not cluster_controller:
        raise HTTPException(status_code=503, detail="Clustering not enabled")
        
    leader_info = cluster_controller.get_leader_info()
    if leader_info:
        return leader_info
    else:
        raise HTTPException(status_code=503, detail="No leader elected")

@app.get("/cluster/health")
async def cluster_health_check():
    """Cluster-aware health check that includes leadership status"""
    if not cluster_controller:
        return {
            "status": "healthy",
            "clustering": "disabled",
            "timestamp": time.time(),
            "version": "1.0.0"
        }
        
    cluster_status = cluster_controller.get_cluster_status()
    is_ready = cluster_controller.is_cluster_ready()
    
    return {
        "status": "healthy" if is_ready else "degraded",
        "clustering": "enabled",
        "node_id": cluster_status["node_id"],
        "state": cluster_status["state"],
        "is_leader": cluster_status["is_leader"],
        "leader_id": cluster_status["leader_id"],
        "cluster_size": cluster_status["cluster_size"],
        "cluster_ready": is_ready,
        "timestamp": time.time(),
        "version": "1.0.0"
    }
```

## Load Balancer Integration

Nginx is configured to route traffic appropriately based on operation type:

### Configuration Structure

```nginx
# Upstream for read operations - can distribute load to all healthy nodes
upstream controller_cluster_read {
    server controller-1:8001 max_fails=3 fail_timeout=30s;
    server controller-2:8002 max_fails=3 fail_timeout=30s;
    server controller-3:8003 max_fails=3 fail_timeout=30s;
}

# Upstream for write operations - only to current leader
upstream controller_cluster_write {
    server controller-1:8001 max_fails=3 fail_timeout=30s;
    server controller-2:8002 max_fails=3 fail_timeout=30s backup;
    server controller-3:8003 max_fails=3 fail_timeout=30s backup;
}

# Map to determine if a request needs to go to the leader
map $request_method $needs_leader {
    default "no";
    POST "yes";
    PUT "yes";
    DELETE "yes";
    PATCH "yes";
}

server {
    listen 8000;
    
    # Read operations - distribute to all healthy nodes
    location ~ ^/(apps/[^/]+/status|apps/[^/]+/metrics|cluster/status|cluster/health)$ {
        proxy_pass http://controller_cluster_read;
        add_header X-Controller-Mode "read-distributed" always;
    }
    
    # Write operations - must go to leader only
    location / {
        proxy_pass http://controller_cluster_write;
        add_header X-Controller-Mode "leader-only" always;
    }
}
```

## Failure Scenarios and Recovery

### 1. Leader Failure

**Scenario**: Current leader node crashes or becomes unresponsive

**Detection**: 
- Leader lease expires (not renewed within `lease_ttl`)
- Health checks fail
- Heartbeat timeouts

**Recovery Process**:
1. Remaining nodes detect expired lease
2. Election timeout triggers on followers
3. First candidate to acquire new lease becomes leader
4. New leader broadcasts its status
5. Load balancer updates routing

**Timeline**: Typically 15-30 seconds for complete failover

### 2. Network Partition

**Scenario**: Network split isolates nodes

**Protection**: 
- Database-based coordination prevents split-brain
- Only node with database access can be leader
- Isolated nodes automatically step down

**Recovery**: 
- When partition heals, nodes rejoin cluster
- Existing leader maintains control
- Isolated nodes sync state from leader

### 3. Database Connectivity Issues

**Scenario**: PostgreSQL becomes unreachable

**Behavior**:
- Current leader steps down when lease renewal fails
- No new leader can be elected
- System enters degraded state
- Read-only operations may continue from cached state

**Recovery**:
- When database connectivity restores, election resumes
- New leader elected within one election cycle
- Full functionality restored

### 4. Load Balancer Failover Mechanism

**Problem Solved**: Ensures requests reach the current leader even during leadership transitions.

**How It Works**:
1. **Non-Leader Response**: When a non-leader controller receives a write request, it returns HTTP 503 (Service Unavailable) instead of redirecting
2. **Nginx Failover**: The load balancer automatically tries the next controller in the upstream pool when it receives a 503 response
3. **Leader Discovery**: Nginx continues trying controllers until it reaches the current leader
4. **Consistent Routing**: All client requests go through the load balancer, preventing direct access to individual controllers

**Key Benefits**:
- **No Redirect Loops**: Clients always interact with the load balancer, never individual controllers
- **Automatic Failover**: No manual intervention needed during leader changes  
- **Fast Recovery**: Typically 1-3 seconds to route to new leader after election
- **Transparent to Clients**: Client applications don't need to know about leadership changes

**Implementation Details**:
```nginx
# Nginx upstream configuration tries all controllers
upstream controller_cluster_write {
    server controller-1:8001 max_fails=1 fail_timeout=5s;
    server controller-2:8002 max_fails=1 fail_timeout=5s; 
    server controller-3:8003 max_fails=1 fail_timeout=5s;
}

# Automatic failover on 503 responses
proxy_next_upstream error timeout invalid_header http_503;
```

**Controller Response Strategy**:
- **Leader**: Processes the request normally
- **Non-Leader**: Returns `503 Service Unavailable` with leader information in headers
- **No Leader**: All controllers return `503` until election completes

### 5. Split-Brain Prevention

The system prevents split-brain scenarios through:

1. **Single Source of Truth**: PostgreSQL database is the only authority for leader election
2. **Atomic Operations**: Lease acquisition uses database transactions
3. **Lease Expiry**: Time-based leases automatically expire
4. **Health Monitoring**: Continuous validation of leader status

## Configuration

### Environment Variables

```bash
# Controller cluster configuration
CLUSTER_NODE_ID=controller-1              # Unique node identifier
CLUSTER_HOSTNAME=controller-1.local       # Node hostname
ORCHESTRY_PORT=8001                       # API port for this node

# Timing configuration  
CLUSTER_LEASE_TTL=30                      # Leadership lease duration (seconds)
CLUSTER_HEARTBEAT_INTERVAL=10             # Heartbeat frequency (seconds)  
CLUSTER_ELECTION_TIMEOUT=15               # Election timeout (seconds)

# Database configuration
DATABASE_PRIMARY_HOST=postgres-primary
DATABASE_REPLICA_HOST=postgres-replica
DATABASE_NAME=orchestry
DATABASE_USER=orchestry
DATABASE_PASSWORD=secure_password
```

### Startup Command

```bash
# Start controller with clustering enabled
docker run -d \
  --name controller-1 \
  --network orchestry \
  -e CLUSTER_NODE_ID=controller-1 \
  -e CLUSTER_HOSTNAME=controller-1 \
  -e ORCHESTRY_PORT=8001 \
  -p 8001:8001 \
  orchestry-controller
```

## Monitoring and Observability

### Cluster Events

All leadership changes and cluster events are logged:

```python
def _log_cluster_event(self, event_type: str, event_data: Dict[str, Any]):
    """Log cluster coordination event"""
    try:
        with self._get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO cluster_events (node_id, event_type, event_data)
                    VALUES (%s, %s, %s)
                """, (self.node_id, event_type, json.dumps(event_data)))
                conn.commit()
    except Exception as e:
        logger.error(f"❌ Failed to log cluster event: {e}")
```

### Key Metrics

Monitor these metrics for cluster health:

- **Leadership Duration**: How long each leader serves
- **Election Frequency**: Rate of leadership changes
- **Lease Renewal Success Rate**: Health of leader lease system
- **Node Health**: Heartbeat success rates
- **Failover Time**: Time to elect new leader after failure

### Log Events

Important cluster events to monitor:

- `leader_elected`: New leader elected
- `leader_lost`: Leadership lost/expired
- `node_joined`: New node joined cluster
- `node_left`: Node left cluster
- `election_started`: Leadership election initiated
- `lease_renewed`: Leadership lease renewed
- `cluster_degraded`: Cluster in unhealthy state

## Best Practices

### 1. Cluster Sizing

- **Production**: Use 3-node clusters for optimal fault tolerance
- **Development**: Single node acceptable for testing
- **Scaling**: Odd numbers (3, 5) prevent ties in future voting scenarios

### 2. Network Configuration

- Ensure reliable network connectivity between nodes
- Use dedicated network segments for cluster communication
- Configure appropriate firewall rules for inter-node communication

### 3. Database Configuration

- Use PostgreSQL High Availability setup with replication
- Configure connection pooling for efficient database access
- Monitor database performance and connectivity

### 4. Monitoring

- Set up alerts for leadership changes
- Monitor lease renewal success rates
- Track cluster health metrics
- Log all cluster events for troubleshooting

### 5. Deployment

- Deploy nodes across different availability zones
- Use health checks in orchestration systems
- Implement graceful shutdown procedures
- Test failover scenarios regularly

## Troubleshooting

### Common Issues

1. **Frequent Leadership Changes**
   - Check network stability between nodes
   - Verify database connectivity
   - Review lease timeout settings

2. **Split-Brain Scenarios**
   - Verify database is the single source of truth
   - Check for network partitions
   - Review fencing mechanisms

3. **Slow Failover**
   - Adjust lease TTL and election timeout values
   - Check database query performance
   - Verify node health check intervals

4. **Cluster Not Ready**
   - Ensure minimum number of healthy nodes
   - Check database connectivity
   - Verify node registration

### Debugging Commands

```bash
# Check cluster status
curl http://localhost:8000/cluster/status

# Get current leader
curl http://localhost:8000/cluster/leader

# Health check with cluster info
curl http://localhost:8000/cluster/health

# Check database cluster events
psql -h postgres-primary -U orchestry -d orchestry \
  -c "SELECT * FROM cluster_events ORDER BY timestamp DESC LIMIT 10;"

# Check current lease
psql -h postgres-primary -U orchestry -d orchestry \
  -c "SELECT * FROM leader_lease;"

# Check node status
psql -h postgres-primary -U orchestry -d orchestry \
  -c "SELECT * FROM cluster_nodes ORDER BY last_heartbeat DESC;"
```

---

**Next Steps**: 
- [Database Architecture](database.md) - Learn about PostgreSQL HA setup
- [Load Balancing](load-balancing.md) - Understand traffic routing
- [Health Monitoring](health.md) - Explore health check systems
