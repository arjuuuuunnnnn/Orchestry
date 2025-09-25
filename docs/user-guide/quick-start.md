# Quick Start Guide

Get AutoServe up and running in minutes and deploy your first application.

## Prerequisites

- **Docker** (20.10+) and **Docker Compose** (v2.0+)
- **Python** 3.8+ (for CLI)
- **Linux/macOS** (Windows with WSL2)
- At least 2GB RAM and 10GB disk space

## Installation

### Option 1: Single Node Setup (Development)

```bash
# Clone the repository
git clone https://github.com/arjuuuuunnnnn/AutoServe.git
cd AutoServe

# Run the quick start script
./start.sh
```

This script will:
- Start a single AutoServe controller
- Set up the PostgreSQL database
- Configure Nginx load balancer
- Install the CLI tool

### Option 2: Distributed Cluster Setup (Production)

```bash
# Clone the repository
git clone https://github.com/arjuuuuunnnnn/AutoServe.git
cd AutoServe

# Start the 3-node distributed cluster
./start-cluster.sh
```

This script will:
- Start 3 controller nodes with leader election
- Set up PostgreSQL HA cluster (primary + replica)
- Configure load balancer for cluster routing
- Initialize cluster coordination
- Install the CLI tool

**Note**: For production deployments, use the distributed cluster setup for high availability.

### Option 2: Manual Setup

```bash
# 1. Clone the repository
git clone https://github.com/arjuuuuunnnnn/AutoServe.git
cd AutoServe

# 2. Start services with Docker Compose
docker-compose up -d

# 3. Install the CLI
pip install -e .

# 4. Verify installation
autoserve --help
```

## Verification

### Single Node Setup

Check that all services are running:

```bash
# Check service status
docker-compose ps

# Verify API is accessible
curl http://localhost:8000/health

# Test CLI
autoserve list
```

You should see:
- ✅ `autoserve-controller` - Main orchestration service
- ✅ `autoserve-postgres-primary` - Primary database
- ✅ `autoserve-postgres-replica` - Replica database
- ✅ `autoserve-nginx` - Load balancer

### Distributed Cluster Setup

Check cluster status:

```bash
# Check cluster health
curl http://localhost:8000/cluster/health

# Get cluster status
curl http://localhost:8000/cluster/status

# Check current leader
curl http://localhost:8000/cluster/leader

# View all services
docker-compose ps
```

You should see:
- ✅ `controller-1`, `controller-2`, `controller-3` - Controller cluster nodes
- ✅ `postgres-primary`, `postgres-replica` - PostgreSQL HA cluster
- ✅ `nginx-lb` - Load balancer with cluster routing
- 👑 One controller node elected as leader

## Deploying Your First App

### Step 1: Create Application Specification

Create a file called `my-app.yml`:

```yaml
apiVersion: v1
kind: App
metadata:
  name: my-web-app
  labels:
    app: "my-web-app"
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
  environment:
    - name: ENV
      value: "production"
scaling:
  mode: auto
  minReplicas: 1
  maxReplicas: 5
  targetRPSPerReplica: 50
  maxP95LatencyMs: 250
  scaleOutThresholdPct: 80
  scaleInThresholdPct: 30
healthCheck:
  path: "/"
  port: 80
  initialDelaySeconds: 10
  periodSeconds: 30
```

### Step 2: Register the Application

```bash
autoserve register my-app.yml
```

### Step 3: Start the Application

```bash
autoserve up my-web-app
```

### Step 4: Check Status

```bash
# View application status
autoserve status my-web-app

# List all applications
autoserve list

# View application logs
autoserve logs my-web-app
```

### Step 5: Test Your Application

Your application is now accessible through the load balancer:

```bash
# Test the application
curl http://localhost/my-web-app

# Or open in browser
open http://localhost/my-web-app
```

## Scaling Your Application

### Manual Scaling

```bash
# Scale to 3 replicas
autoserve scale my-web-app 3

# Scale down to 1 replica
autoserve scale my-web-app 1
```

### Auto-Scaling

AutoServe automatically scales based on:
- **CPU utilization** (target: 70%)
- **Memory usage** (target: 75%)
- **Requests per second** (50 RPS per replica)
- **Response latency** (P95 < 250ms)
- **Active connections** (80 per replica)

Monitor scaling decisions:

```bash
# View scaling events
autoserve events my-web-app

# View current metrics
autoserve metrics my-web-app
```

## Management Commands

```bash
# Stop application
autoserve down my-web-app

# Remove application
autoserve remove my-web-app

# View all applications
autoserve list

# Get application details
autoserve describe my-web-app

# View system status
autoserve status
```

## Configuration

### Environment Variables

Configure AutoServe behavior with environment variables:

```bash
# Controller API settings
export AUTOSERVE_HOST=localhost
export AUTOSERVE_PORT=8000

# Database settings
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export POSTGRES_DB=autoserve
export POSTGRES_USER=autoserve
export POSTGRES_PASSWORD=autoserve_password

# Scaling settings
export DEFAULT_SCALE_CHECK_INTERVAL=30
export DEFAULT_HEALTH_CHECK_INTERVAL=10
```

### Cluster Mode

For high availability, run AutoServe in cluster mode:

```bash
# Start cluster
./start-cluster.sh

# Check cluster status
autoserve cluster status
```

## Next Steps

Now that you have AutoServe running:

1. **Learn the CLI**: Check out the [CLI Reference](cli-reference.md)
2. **Understand App Specs**: Read the [Application Specification](app-spec.md) guide
3. **Explore the API**: See the [REST API Reference](api-reference.md)
4. **Configure Scaling**: Dive into [Configuration Guide](configuration.md)
5. **Monitor Applications**: Learn about [health monitoring](../developer-guide/health.md)

## Getting Help

- **Documentation**: Browse the complete docs
- **Examples**: Check the `examples/` directory
- **Issues**: Report bugs on GitHub
- **Community**: Join our discussions

---

**Troubleshooting**: If you encounter issues, see the [Troubleshooting Guide](troubleshooting.md).