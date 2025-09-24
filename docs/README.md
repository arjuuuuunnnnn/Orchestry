# AutoServe Documentation

Welcome to AutoServe - a lightweight container orchestration and auto-scaling platform designed for web applications.

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
- [Database Schema](developer-guide/database.md) - State management and persistence
- [Scaling Algorithm](developer-guide/scaling.md) - Auto-scaling logic and policies
- [Health Monitoring](developer-guide/health.md) - Health check system
- [Load Balancing](developer-guide/load-balancing.md) - Nginx integration and routing
- [Development Setup](developer-guide/development.md) - Contributing to AutoServe
- [Extension Guide](developer-guide/extensions.md) - Adding new features

### Examples
- [Sample Applications](examples/applications.md) - Real-world application examples
- [Deployment Scenarios](examples/deployments.md) - Different deployment patterns
- [Load Testing](examples/load-testing.md) - Performance testing examples

## What is AutoServe?

AutoServe is a container orchestration platform that provides:

- **Intelligent Auto-Scaling**: Automatically scales your applications based on CPU, memory, RPS, latency, and connection metrics
- **Load Balancing**: Dynamic Nginx configuration with health-aware routing
- **Health Monitoring**: Continuous health checks with automatic recovery
- **Simple Deployment**: YAML-based application specifications
- **RESTful API**: Complete programmatic control
- **High Availability**: PostgreSQL-based state management with replication

## Key Features

- Container orchestration with Docker
- Multi-metric auto-scaling (CPU, memory, RPS, latency, connections)
- Dynamic load balancing with Nginx
- Health monitoring and automatic recovery
- CLI and REST API interfaces
- Persistent state with PostgreSQL
- Event logging and audit trails
- Resource constraints and scaling policies

## Quick Links

- [Installation](user-guide/quick-start.md#installation)
- [Your First Application](user-guide/quick-start.md#deploying-your-first-app)
- [CLI Commands](user-guide/cli-reference.md)
- [API Endpoints](user-guide/api-reference.md)
- [Architecture](developer-guide/architecture.md)

---

*AutoServe v1.0.0 - Built for simplicity, designed for scale*