# AutoServe Documentation

Welcome to AutoServe - A lightweight container orchestration and auto-scaling platform designed for web applications.

## Documentation Structure

### For Users
- [Quick Start Guide](user-guide/quick-start.md) - Get up and running in minutes
- [CLI Reference](user-guide/cli-reference.md) - Complete command-line interface documentation
- [Application Specification](user-guide/app-spec.md) - How to define your applications
- [Configuration Guide](user-guide/configuration.md) - Environment and scaling configuration
- [REST API Reference](user-guide/api-reference.md) - HTTP API endpoints and usage
- [Troubleshooting](user-guide/troubleshooting.md) - Common issues and solutions

### For Developers
- [Architecture Overview](developer-guide/architecture.md) - System design and components
- [Core Components](developer-guide/components.md) - Detailed component documentation
- [Leader Election](developer-guide/leader-election.md) - Distributed controller and high availability
- [Database Schema](developer-guide/database.md) - State management and persistence
- [Scaling Algorithm](developer-guide/scaling.md) - Auto-scaling logic and policies
- [Health Monitoring](developer-guide/health.md) - Health check system
- [Load Balancing](developer-guide/load-balancing.md) - Nginx integration and routing
- [Development Setup](developer-guide/development.md) - Contributing to AutoServe
- [Extension Guide](developer-guide/extensions.md) - Adding new features

### Examples
- [Sample Applications](examples/applications.md) - Real-world application examples

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

- [Installation](user-guide/quick-start.md#installation)
- [Your First Application](user-guide/quick-start.md#deploying-your-first-app)
- [CLI Commands](user-guide/cli-reference.md)
- [API Endpoints](user-guide/api-reference.md)
- [Architecture](developer-guide/architecture.md)

---

*AutoServe v1.0.0 - Built for simplicity, designed for scale*