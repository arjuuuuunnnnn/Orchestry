# AutoServe Documentation

Welcome to AutoServe - A lightweight container orchestration and auto-scaling platform designed for web applications

## Documentation Structure

### For Users
- [Quick Start Guide](docs/user-guide/quick-start.md) - Get up and running in minutes
- [CLI Reference](docs/user-guide/cli-reference.md) - Complete command-line interface documentation
- [Application Specification](docs/user-guide/app-spec.md) - How to define your applications
- [Configuration Guide](docs/user-guide/configuration.md) - Environment and scaling configuration
- [REST API Reference](docs/user-guide/api-reference.md) - HTTP API endpoints and usage
- [Troubleshooting](docs/user-guide/troubleshooting.md) - Common issues and solutions

### For Developers
- [Architecture Overview](docs/developer-guide/architecture.md) - System design and components
- [Core Components](docs/developer-guide/components.md) - Detailed component documentation
- [Leader Election](docs/developer-guide/leader-election.md) - Distributed controller and high availability
- [Database Schema](docs/developer-guide/database.md) - State management and persistence
- [Scaling Algorithm](docs/developer-guide/scaling.md) - Auto-scaling logic and policies
- [Health Monitoring](docs/developer-guide/health.md) - Health check system
- [Load Balancing](docs/developer-guide/load-balancing.md) - Nginx integration and routing
- [Development Setup](docs/developer-guide/development.md) - Contributing to AutoServe
- [Extension Guide](docs/developer-guide/extensions.md) - Adding new features

### Examples
- [Sample Applications](docs/examples/applications.md) - Real-world application examples
- [Deployment Scenarios](docs/examples/deployments.md) - Different deployment patterns
- [Load Testing](docs/examples/load-testing.md) - Performance testing examples

## What is AutoServe?

AutoServe is a container orchestration platform that provides:

- **Intelligent Auto-Scaling**: Automatically scales your applications based on CPU, memory, RPS, latency, and connection metrics
- **Load Balancing**: Dynamic Nginx configuration with health-aware routing
- **Health Monitoring**: Continuous health checks with automatic recovery
- **Simple Deployment**: YAML-based application specifications
- **RESTful API**: Complete programmatic control
- **High Availability**: Distributed controller with leader election eliminates single points of failure
- **Database HA**: PostgreSQL-based state management with primary-replica replication

## Key Features

- **Container Orchestration**: Docker-based application lifecycle management
- **Multi-Metric Auto-Scaling**: CPU, memory, RPS, latency, and connection-based scaling
- **Dynamic Load Balancing**: Nginx with health-aware routing and SSL termination
- **Health Monitoring**: Continuous health checks with automatic recovery
- **Distributed Architecture**: 3-node controller cluster with leader election
- **High Availability**: Automatic failover and split-brain prevention
- **CLI and REST API**: Complete programmatic and command-line interfaces
- **Persistent State**: PostgreSQL with primary-replica setup
- **Event Logging**: Complete audit trail and cluster event tracking
- **Resource Management**: CPU/memory constraints and intelligent scaling policies 

## Quick Links

- [Installation](docs/user-guide/quick-start.md#installation)
- [Your First Application](docs/user-guide/quick-start.md#deploying-your-first-app)
- [CLI Commands](docs/user-guide/cli-reference.md)
- [API Endpoints](docs/user-guide/api-reference.md)
- [Architecture](docs/developer-guide/architecture.md)

---

*AutoServe v1.0.0 - Built for simplicity, designed for scale*
