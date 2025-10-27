# Troubleshooting Guide

Common issues, solutions, and debugging techniques for Orchestry.

## Quick Diagnosis

### Service Status Check

First, verify all services are running:

```bash
# Check Orchestry services
docker-compose ps

# Check API health
curl http://localhost:8000/health

# Check database connectivity
docker exec -it orchestry-postgres-primary psql -U orchestry -d orchestry -c "SELECT 1;"

# Check nginx status
docker exec -it orchestry-nginx nginx -t
```

### Common Status Issues

| Service Status | Possible Cause | Solution |
|---------------|----------------|----------|
| `orchestry-controller` Exited | Configuration error | Check logs: `docker logs orchestry-controller` |
| `orchestry-postgres-primary` Unhealthy | Database startup issue | Check DB logs: `docker logs orchestry-postgres-primary` |
| `orchestry-nginx` Restarting | Config syntax error | Validate nginx config: `nginx -t` |

## Application Issues

### Application Won't Start

**Symptoms:**
- Application status shows "error" or "failed"
- Containers are not created
- API returns 500 errors

**Diagnostic Steps:**

```bash
# Check application status
orchestry status my-app

# View application events
orchestry events my-app

# Check Docker daemon
docker info

# Verify image exists
docker pull my-app:latest

# Check network configuration
docker network ls | grep orchestry
```

**Common Causes and Solutions:**

#### 1. Image Pull Errors

```bash
# Error: "pull access denied" or "image not found"
# Solution: Verify image name and registry access
docker login myregistry.com
docker pull myregistry.com/my-app:v1.0.0
```

#### 2. Resource Constraints

```bash
# Error: "insufficient memory" or "insufficient cpu"
# Check system resources
docker system df
docker stats

# Solution: Increase limits or reduce resource requests
```

```yaml
# Reduce resource requirements
spec:
  resources:
    cpu: "100m"    # Reduced from 1000m
    memory: "256Mi" # Reduced from 1Gi
```

#### 3. Port Conflicts

```bash
# Error: "port already in use"
# Check port usage
netstat -tulpn | grep :8000
docker ps --format "table {{.Names}}\t{{.Ports}}"

# Solution: Use different ports or stop conflicting services
```

#### 4. Environment Variable Issues

```bash
# Check container logs for env var errors
orchestry logs my-app --tail 50

# Common issues:
# - Missing required environment variables
# - Invalid database URLs
# - Incorrect service endpoints
```

### Application Crashes Repeatedly

**Symptoms:**
- Container keeps restarting
- Health checks failing
- High failure count in status

**Diagnostic Steps:**

```bash
# Check crash logs
orchestry logs my-app --since 1h

# View container restart events
orchestry events my-app --type error

# Check resource usage
docker stats $(docker ps -q --filter "label=orchestry.app=my-app")
```

**Common Solutions:**

#### 1. Memory Issues (OOM Kills)

```bash
# Check for OOM kills in system logs
dmesg | grep -i "killed process"
journalctl -u docker.service | grep -i "oom"
```

**Solution:**
```yaml
# Increase memory limits
spec:
  resources:
    memory: "2Gi"  # Increased from 1Gi
    
# Or optimize application memory usage
environment:
  - name: NODE_OPTIONS
    value: "--max-old-space-size=1536"  # For Node.js apps
```

#### 2. Health Check Failures

```bash
# Test health check manually
curl -f http://container-ip:port/health

# Check health check configuration
orchestry describe my-app --show-spec | grep -A 10 healthCheck
```

**Solution:**
```yaml
# Adjust health check settings
healthCheck:
  path: "/health"
  port: 8080
  initialDelaySeconds: 60  # Increased startup time
  periodSeconds: 30
  timeoutSeconds: 10       # Increased timeout
  failureThreshold: 5      # More tolerance
```

#### 3. Dependency Issues

```bash
# Check if app depends on external services
orchestry logs my-app | grep -i "connection\|database\|redis\|timeout"
```

**Solution:**
```yaml
# Add dependency health checks and retries
environment:
  - name: DB_RETRY_ATTEMPTS
    value: "10"
  - name: DB_RETRY_DELAY
    value: "5"
```

## Scaling Issues

### Application Not Scaling

**Symptoms:**
- Load increases but replica count stays same
- Scaling events show "no scaling needed"
- Manual scaling works but auto-scaling doesn't

**Diagnostic Steps:**

```bash
# Check scaling policy
orchestry describe my-app | grep -A 20 scaling

# View scaling events
orchestry events my-app --type scaling

# Check current metrics
orchestry metrics my-app

# Verify auto-scaling is enabled
orchestry status my-app | grep -i mode
```

**Common Causes and Solutions:**

#### 1. Scaling Mode Set to Manual

```bash
# Check current mode
orchestry describe my-app | grep mode

# Solution: Enable auto scaling
curl -X PUT http://localhost:8000/api/v1/apps/my-app/scaling \
  -H "Content-Type: application/json" \
  -d '{"mode": "auto"}'
```

#### 2. In Cooldown Period

```bash
# Check last scaling event
orchestry events my-app --type scaling --limit 1

# If recent scaling occurred, wait for cooldown period
# Default cooldown is 180 seconds
```

#### 3. Metrics Below Threshold

```bash
# Check current metrics vs thresholds
orchestry metrics my-app --format json | jq '.current'

# View scaling thresholds
orchestry describe my-app | grep -i threshold
```

**Solution:**
```yaml
# Adjust scaling thresholds
scaling:
  scaleOutThresholdPct: 60  # Reduced from 80
  scaleInThresholdPct: 20   # Reduced from 30
```

#### 4. Insufficient Resources

```bash
# Check system resources
docker system df
docker stats --no-stream

# Check Docker daemon limits
docker info | grep -i memory
```

### Scaling Too Aggressive/Conservative

**Symptoms:**
- Application scales up/down too frequently
- Resource waste due to over-provisioning
- Performance issues due to under-provisioning

**Solutions:**

#### Too Aggressive Scaling

```yaml
# Increase cooldown period
scaling:
  cooldownSeconds: 300  # Increased from 180
  
# Make thresholds more conservative
scaling:
  scaleOutThresholdPct: 85  # Increased from 80
  scaleInThresholdPct: 15   # Decreased from 30
  
# Increase evaluation window
scaling:
  windowSeconds: 120  # Increased from 60
```

#### Too Conservative Scaling

```yaml
# Decrease cooldown period
scaling:
  cooldownSeconds: 120  # Decreased from 180
  
# Make thresholds more aggressive
scaling:
  scaleOutThresholdPct: 70  # Decreased from 80
  scaleInThresholdPct: 40   # Increased from 30
```

## Network and Load Balancing Issues

### Application Not Accessible

**Symptoms:**
- Application status shows "running" but requests fail
- 502/503 errors from load balancer
- Connection timeouts

**Diagnostic Steps:**

```bash
# Check nginx configuration
docker exec orchestry-nginx nginx -t

# View nginx error logs
docker logs orchestry-nginx

# Check upstream configuration
docker exec orchestry-nginx cat /etc/nginx/conf.d/my-app.conf

# Test container directly
docker exec -it my-app-1 curl localhost:8080/health
```

**Common Solutions:**

#### 1. Nginx Configuration Errors

```bash
# Check nginx config syntax
docker exec orchestry-nginx nginx -t

# Reload nginx configuration
docker exec orchestry-nginx nginx -s reload

# View generated upstream config
docker exec orchestry-nginx ls -la /etc/nginx/conf.d/
```

#### 2. Container Network Issues

```bash
# Check container network connectivity
docker network inspect orchestry

# Verify container IPs
docker inspect my-app-1 | jq '.[0].NetworkSettings.Networks.orchestry.IPAddress'

# Test inter-container connectivity
docker exec orchestry-nginx ping container-ip
```

#### 3. Health Check Failures

```bash
# Check container health status
orchestry status my-app

# Test health checks manually
curl http://container-ip:port/health

# Check health check logs
orchestry events my-app --type health
```

### Load Distribution Issues

**Symptoms:**
- Uneven load distribution across replicas
- Some containers overloaded while others idle
- Inconsistent response times

**Solutions:**

#### 1. Nginx Load Balancing Method

```bash
# Check current load balancing method
docker exec orchestry-nginx grep -r "least_conn\|ip_hash" /etc/nginx/conf.d/

# For session-less apps, use least_conn (default)
# For session-based apps, consider ip_hash
```

#### 2. Container Resource Imbalance

```bash
# Check resource usage per container
docker stats --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}"

# Ensure containers have same resource limits
orchestry describe my-app | grep -A 5 resources
```

## Database Issues

### Database Connection Errors

**Symptoms:**
- Applications can't connect to database
- Connection timeout errors
- "too many connections" errors

**Diagnostic Steps:**

```bash
# Check database status
docker logs orchestry-postgres-primary

# Test database connectivity
docker exec -it orchestry-postgres-primary psql -U orchestry -d orchestry -c "SELECT 1;"

# Check active connections
docker exec -it orchestry-postgres-primary psql -U orchestry -d orchestry -c "SELECT count(*) FROM pg_stat_activity;"

# Verify connection string format
echo $DATABASE_URL
```

**Solutions:**

#### 1. Connection Pool Exhaustion

```bash
# Check max connections
docker exec -it orchestry-postgres-primary psql -U orchestry -d orchestry -c "SHOW max_connections;"

# Increase max connections
# Edit postgresql.conf or use environment variable
```

```yaml
# In docker-compose.yml
environment:
  POSTGRES_MAX_CONNECTIONS: 200
```

#### 2. Network Connectivity

```bash
# Test network connectivity from app container
docker exec -it my-app-1 nc -zv postgres-host 5432

# Check Docker network
docker network inspect orchestry
```

#### 3. Authentication Issues

```bash
# Check pg_hba.conf settings
docker exec orchestry-postgres-primary cat /var/lib/postgresql/data/pg_hba.conf

# Test authentication
docker exec -it orchestry-postgres-primary psql -U orchestry -h localhost -d orchestry
```

### Database Performance Issues

**Symptoms:**
- Slow query response times
- Database CPU/memory high
- Application timeouts

**Solutions:**

#### 1. Resource Allocation

```yaml
# Increase database resources
services:
  postgres-primary:
    environment:
      POSTGRES_SHARED_BUFFERS: 256MB
      POSTGRES_EFFECTIVE_CACHE_SIZE: 1GB
    deploy:
      resources:
        limits:
          memory: 4G
          cpus: '2.0'
```

#### 2. Connection Pooling

```bash
# Implement connection pooling in applications
# Use pgbouncer or application-level pooling
```

```yaml
# Application configuration
environment:
  - name: DB_POOL_SIZE
    value: "10"
  - name: DB_POOL_TIMEOUT
    value: "30"
```

## Performance Issues

### High Latency

**Symptoms:**
- Response times consistently high
- P95 latency above thresholds
- User complaints about slow responses

**Diagnostic Steps:**

```bash
# Check application metrics
orchestry metrics my-app

# View scaling decisions
orchestry events my-app --type scaling

# Check resource utilization
docker stats my-app-1 my-app-2 my-app-3

# Test response times directly
curl -w "%{time_total}\n" -o /dev/null -s http://localhost/my-app/
```

**Solutions:**

#### 1. Scale Out Application

```bash
# Manual scaling
orchestry scale my-app 5

# Or adjust auto-scaling thresholds
```

```yaml
scaling:
  maxP95LatencyMs: 200      # Reduced threshold
  scaleOutThresholdPct: 70  # Scale out earlier
```

#### 2. Optimize Resource Allocation

```yaml
# Increase CPU allocation
spec:
  resources:
    cpu: "2000m"  # Increased from 1000m
    memory: "2Gi"
```

#### 3. Add Caching

```yaml
# Add Redis cache
environment:
  - name: REDIS_URL
    value: "redis://redis.example.com:6379"
  - name: CACHE_TTL
    value: "300"
```

### High Memory Usage

**Symptoms:**
- Containers being OOM killed
- Memory usage consistently high
- Frequent container restarts

**Solutions:**

#### 1. Increase Memory Limits

```yaml
spec:
  resources:
    memory: "4Gi"  # Increased from 2Gi
```

#### 2. Optimize Application

```yaml
# For Node.js applications
environment:
  - name: NODE_OPTIONS
    value: "--max-old-space-size=3072"
    
# For Java applications
environment:
  - name: JAVA_OPTS
    value: "-Xms1g -Xmx3g -XX:+UseG1GC"
```

#### 3. Memory Profiling

```bash
# Enable memory profiling
# Add profiling tools to container
# Monitor memory usage patterns
```

## Monitoring and Debugging

### Insufficient Logging

**Problem:** Can't debug issues due to lack of logs

**Solutions:**

#### 1. Increase Log Levels

```yaml
environment:
  - name: LOG_LEVEL
    value: "DEBUG"  # Temporarily for debugging
  - name: DEBUG
    value: "*"      # For debug module
```

#### 2. Structured Logging

```yaml
environment:
  - name: LOG_FORMAT
    value: "json"
  - name: LOG_TIMESTAMP
    value: "true"
```

#### 3. Log Aggregation

```bash
# View logs from all replicas
orchestry logs my-app --follow

# View specific time range
orchestry logs my-app --since 2h --until 1h
```

### Missing Metrics

**Problem:** Can't monitor application performance

**Solutions:**

#### 1. Enable Application Metrics

```yaml
# Add metrics endpoint
ports:
  - containerPort: 8080
    name: "api"
  - containerPort: 9090
    name: "metrics"

environment:
  - name: METRICS_ENABLED
    value: "true"
  - name: METRICS_PORT
    value: "9090"
```

#### 2. Custom Health Checks

```yaml
healthCheck:
  path: "/health/detailed"
  port: 8080
  headers:
    - name: "X-Health-Check"
      value: "orchestry"
```

## Configuration Issues

### Environment Variable Problems

**Symptoms:**
- Application fails to start
- Feature flags not working
- Database connections failing

**Solutions:**

#### 1. Validate Environment Variables

```bash
# Check container environment
docker exec my-app-1 env | grep MY_VAR

# Validate in application specification
orchestry describe my-app | grep -A 20 environment
```

#### 2. Secret Management

```yaml
# Use secrets for sensitive data
environment:
  - name: DATABASE_PASSWORD
    source: secret
    key: "db-credentials"
    field: "password"
```

#### 3. Configuration Validation

```bash
# Add configuration validation to application startup
# Log all configuration values (except secrets)
# Fail fast on missing required configuration
```

## Recovery Procedures

### Complete System Recovery

If Orchestry is completely down:

```bash
# 1. Stop all services
docker-compose down

# 2. Check for disk space issues
df -h
docker system prune -f

# 3. Restart services
docker-compose up -d

# 4. Wait for services to be healthy
docker-compose ps

# 5. Verify database connectivity
docker exec -it orchestry-postgres-primary psql -U orchestry -d orchestry -c "SELECT count(*) FROM applications;"

# 6. Restart applications
orchestry list
for app in $(orchestry list --format json | jq -r '.apps[].name'); do
  orchestry up $app
done
```

### Database Recovery

If database is corrupted:

```bash
# 1. Stop Orchestry
docker-compose stop orchestry-controller

# 2. Backup current database
docker exec orchestry-postgres-primary pg_dump -U orchestry orchestry > backup.sql

# 3. Check database integrity
docker exec -it orchestry-postgres-primary psql -U orchestry -d orchestry -c "SELECT pg_database_size('orchestry');"

# 4. If needed, restore from backup
docker exec -i orchestry-postgres-primary psql -U orchestry -d orchestry < backup.sql

# 5. Restart services
docker-compose up -d
```

### Application Recovery

If specific application is stuck:

```bash
# 1. Stop application
orchestry down my-app --force

# 2. Clean up containers
docker rm -f $(docker ps -aq --filter "label=orchestry.app=my-app")

# 3. Clear application state (if needed)
# This will lose scaling history but preserve configuration
curl -X DELETE http://localhost:8000/api/v1/apps/my-app/instances

# 4. Restart application
orchestry up my-app

# 5. Monitor startup
orchestry logs my-app --follow
```

## Cluster and Leader Election Issues

### Requests Not Reaching Current Leader

**Symptoms:**
- Write operations (POST, PUT, DELETE) return 503 Service Unavailable
- API returns "Not the leader" errors after leader failover
- Applications not updating despite API calls

**Diagnostic Steps:**

```bash
# Check cluster status
curl http://localhost:8000/cluster/status

# Check current leader
curl http://localhost:8000/cluster/leader

# Check individual controller health  
curl http://localhost:8001/health  # Controller 1
curl http://localhost:8002/health  # Controller 2
curl http://localhost:8003/health  # Controller 3

# Check controller load balancer logs
docker logs orchestry-controller-lb

# Check if load balancer is routing correctly
curl -H "X-Debug: true" http://localhost:8000/cluster/leader
```

**Common Causes and Solutions:**

#### 1. Load Balancer Not Routing to Current Leader

The load balancer should automatically route write operations to the current leader. If this isn't working:

```bash
# Check nginx upstream configuration
docker exec orchestry-controller-lb cat /etc/nginx/conf.d/default.conf

# Verify all controllers are reachable
docker exec orchestry-controller-lb nslookup controller-1
docker exec orchestry-controller-lb nslookup controller-2  
docker exec orchestry-controller-lb nslookup controller-3

# Check nginx error logs for upstream failures
docker logs orchestry-controller-lb | grep -i error
```

**Solution:** The system now uses nginx failover. When a non-leader controller receives a write request, it returns 503, causing nginx to try the next controller until it finds the leader.

#### 2. Leader Election Split-Brain

**Symptoms:**
- Multiple controllers claim to be leader
- Inconsistent cluster status from different controllers

```bash
# Check each controller's view of leadership
for port in 8001 8002 8003; do
  echo "Controller $port leadership status:"
  curl -s http://localhost:$port/cluster/status | jq '.is_leader'
done

# Check database lease table
docker exec -it orchestry-postgres-primary psql -U orchestry -d orchestry -c "SELECT * FROM leader_lease ORDER BY term DESC LIMIT 5;"
```

**Solution:**
```bash
# Force leadership release (from current leader)
curl -X DELETE http://localhost:8000/api/v1/cluster/leadership

# Restart all controllers to re-trigger election
docker-compose restart controller-1 controller-2 controller-3
```

#### 3. Stale Leader Information

**Symptoms:**
- Clients redirected to dead leader
- API calls timeout or return connection errors

```bash
# Check if leader info is stale
LEADER_URL=$(curl -s http://localhost:8000/cluster/leader | jq -r '.api_url')
curl -f $LEADER_URL/health || echo "Leader not reachable"

# Check leader lease expiration
curl -s http://localhost:8000/cluster/leader | jq '.lease_expires_at'
date +%s  # Compare with current timestamp
```

**Solution:** The new implementation always redirects clients to the load balancer, not individual controllers, preventing stale leader issues.

#### 4. Network Partitioning

**Symptoms:**
- Some controllers can't reach database
- Controllers in different network states

```bash
# Test database connectivity from each controller
for service in controller-1 controller-2 controller-3; do
  echo "Testing $service database connectivity:"
  docker exec $service nc -zv postgres-primary 5432
done

# Check network partitions
docker network inspect orchestry
```

### Leader Election Taking Too Long

**Symptoms:**
- No leader elected for extended periods
- Cluster shows "No leader elected" status
- Write operations return 503 for long periods

**Diagnostic Steps:**

```bash
# Check election process
docker logs orchestry-controller-1 | grep -i "election\|leader"
docker logs orchestry-controller-2 | grep -i "election\|leader"  
docker logs orchestry-controller-3 | grep -i "election\|leader"

# Check database lease attempts
docker exec -it orchestry-postgres-primary psql -U orchestry -d orchestry -c "SELECT * FROM leader_lease ORDER BY acquired_at DESC LIMIT 10;"

# Monitor election attempts
curl -s http://localhost:8000/cluster/status | jq '.election_status'
```

**Common Causes:**

#### 1. Database Connectivity Issues

```bash
# Test database connectivity
for port in 8001 8002 8003; do
  echo "Controller $port database test:"
  curl -s http://localhost:$port/health | jq '.database'
done
```

#### 2. Clock Synchronization Issues

```bash
# Check system clocks on containers
docker exec controller-1 date
docker exec controller-2 date
docker exec controller-3 date

# Large time differences can cause lease issues
```

#### 3. Resource Constraints

```bash
# Check controller resource usage
docker stats controller-1 controller-2 controller-3 --no-stream

# High CPU/memory usage can delay election processing
```

### Frequent Leader Changes

**Symptoms:**
- Leader changes every few minutes
- Applications experience interruptions
- Scaling decisions inconsistent

**Diagnostic Steps:**

```bash
# Monitor leader changes
watch -n 5 'curl -s http://localhost:8000/cluster/leader | jq .leader_id'

# Check lease renewal logs
docker logs orchestry-controller-1 | grep -i "lease\|renew"

# Check for resource issues
docker stats --no-stream | grep controller
```

**Solutions:**

#### 1. Increase Lease Duration

```yaml
# In controller configuration
environment:
  - name: LEADER_LEASE_TTL
    value: "45"  # Increased from 30 seconds
```

#### 2. Improve Network Stability

```bash
# Check for network issues
docker network inspect orchestry | jq '.Containers'

# Monitor network latency between controllers
```

### Controller Startup Issues

**Symptoms:**
- Controllers fail to join cluster
- Startup errors in logs
- Services not reaching healthy state

**Solutions:**

#### 1. Database Migration Issues

```bash
# Check database schema
docker exec -it orchestry-postgres-primary psql -U orchestry -d orchestry -c "\dt"

# Manually run migrations if needed
docker exec orchestry-controller-1 python -m alembic upgrade head
```

#### 2. Port Conflicts

```bash
# Check port availability
netstat -tulpn | grep -E ":(8001|8002|8003|8000)"

# Ensure ports in .env file match docker-compose.yml
grep -E "CONTROLLER.*PORT" .env.docker
```

#### 3. Environment Configuration

```bash
# Verify required environment variables
docker exec controller-1 env | grep -E "CLUSTER|CONTROLLER|POSTGRES"

# Check for missing variables
docker-compose config | grep -A 10 -B 5 controller-1
```

## Getting Help

### Collecting Diagnostic Information

Before seeking help, collect this information:

```bash
#!/bin/bash
# Orchestry diagnostic script

echo "=== Orchestry Diagnostic Information ==="
echo "Date: $(date)"
echo "Version: $(orchestry --version)"
echo

echo "=== System Information ==="
uname -a
docker --version
docker-compose --version
echo

echo "=== Service Status ==="
docker-compose ps
echo

echo "=== API Health ==="
curl -s http://localhost:8000/health | jq '.' || echo "API not responding"
echo

echo "=== Application Status ==="
orchestry list
echo

echo "=== Recent Events ==="
orchestry events --limit 20
echo

echo "=== System Resources ==="
docker system df
docker stats --no-stream
echo

echo "=== Recent Logs ==="
echo "Controller logs:"
docker logs --tail 50 orchestry-controller
echo
echo "Database logs:"
docker logs --tail 20 orchestry-postgres-primary
echo
echo "Nginx logs:"
docker logs --tail 20 orchestry-nginx
```

### Support Channels

1. **GitHub Issues**: Report bugs and feature requests
2. **Documentation**: Check latest documentation
3. **Community**: Join discussions and ask questions
4. **Enterprise Support**: Contact for enterprise deployments

### Best Practices for Issue Reporting

1. **Include diagnostic information** from the script above
2. **Describe expected vs actual behavior**
3. **Provide minimal reproduction steps**
4. **Include application specifications** (without secrets)
5. **Mention environment details** (OS, Docker version, etc.)

---

**Next Steps**: Learn about [Configuration](configuration.md) for advanced settings and optimizations.