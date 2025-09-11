# AutoServe - Docker-Native SDK

🐳 **Fully containerized autoscaling solution - No system installations required!**

AutoServe is now completely self-contained using Docker containers for all infrastructure components including Nginx, Redis, and the database.

## 🚀 Quick Start

### Prerequisites
- Docker (>= 20.10)
- Docker Compose (>= 2.0)

### Start AutoServe
```bash
# Start the complete system
./start-controller.sh

# Or in development mode with live code reloading
DEV_MODE=true ./start-controller.sh
```

### Test the System
```bash
# Run automated tests
./test-system.sh
```

### Register and Run an App
```bash
# Register an app
curl -X POST http://localhost:8000/apps/register \
  -H "Content-Type: application/json" \
  -d @examples/nginx-demo.json

# Start the app
curl -X POST http://localhost:8000/apps/nginx-demo/up

# Check status
curl http://localhost:8000/apps/nginx-demo/status

# Scale the app
curl -X POST http://localhost:8000/apps/nginx-demo/scale \
  -H "Content-Type: application/json" \
  -d '{"replicas": 3}'

# Test through load balancer
curl -H "Host: nginx-demo.local" http://localhost:80
```

## 🏗️ Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Your Apps     │    │   AutoServe     │    │ Infrastructure  │
│                 │    │   Controller    │    │   Containers    │
│ ┌─────────────┐ │    │                 │    │                 │
│ │ App Replica │ │◀──▶│ ┌─────────────┐ │◀──▶│ ┌─────────────┐ │
│ │ Container   │ │    │ │ FastAPI     │ │    │ │ Nginx       │ │
│ └─────────────┘ │    │ │ API Server  │ │    │ │ Load Bal.   │ │
│ ┌─────────────┐ │    │ └─────────────┘ │    │ └─────────────┘ │
│ │ App Replica │ │    │ ┌─────────────┐ │    │ ┌─────────────┐ │
│ │ Container   │ │    │ │ AutoScaler  │ │    │ │ Redis       │ │
│ └─────────────┘ │    │ │ Engine      │ │    │ │ Cache       │ │
└─────────────────┘    │ └─────────────┘ │    │ └─────────────┘ │
                       │ ┌─────────────┐ │    │ ┌─────────────┐ │
                       │ │ SQLite DB   │ │    │ │ Persistent  │ │
                       │ │ State Store │ │    │ │ Volumes     │ │
                       │ └─────────────┘ │    │ └─────────────┘ │
                       └─────────────────┘    └─────────────────┘
```

## 🌟 Features

- **✅ Zero System Dependencies**: Everything runs in containers
- **✅ Automatic Load Balancing**: Nginx-based with health checks
- **✅ Intelligent Autoscaling**: CPU, memory, and traffic-based
- **✅ Health Monitoring**: HTTP health checks with failover
- **✅ Persistent State**: SQLite database with audit trails
- **✅ REST API**: Complete management interface
- **✅ Docker Native**: Uses Docker API for container management

## 📊 Monitoring

- **Controller API**: http://localhost:8000
- **System Metrics**: http://localhost:8000/metrics
- **App Status**: http://localhost:8000/apps
- **Load Balancer**: http://localhost:80
- **Nginx Status**: http://localhost:80/nginx_status

## 🛠️ Management Commands

```bash
# View running services
docker-compose ps

# View logs
docker-compose logs -f

# Stop services
docker-compose down

# Restart services
docker-compose restart

# Clean up everything
docker-compose down -v --remove-orphans
```

## 🔧 Configuration

Environment variables (set in docker-compose.yml or .env):

```bash
AUTOSERVE_DB_PATH=/app/data/autoscaler.db
AUTOSERVE_NGINX_CONTAINER=autoserve-nginx
AUTOSERVE_REDIS_URL=redis://autoserve-redis:6379
AUTOSERVE_HOST=0.0.0.0
AUTOSERVE_PORT=8000
AUTOSERVE_LOG_LEVEL=INFO
```

## 📖 Documentation

- [Controller README](controller/README.md) - Detailed component documentation
- [Examples](examples/) - Sample app specifications
- [Docker Setup](docker/) - Container configurations

## 🎯 What's New in Docker Mode

1. **🐳 No System Dependencies**: Nginx, Redis, and database run in containers
2. **📦 Easy Setup**: Single command to start everything
3. **🔄 Automatic Networking**: All services connected via Docker networks
4. **💾 Persistent Data**: Volumes for database and configuration
5. **🔍 Health Checks**: Built-in container health monitoring
6. **🚀 Development Mode**: Live code reloading for development

This is now a true SDK - install once, runs anywhere with Docker! 🎉
