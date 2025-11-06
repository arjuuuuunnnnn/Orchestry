# Development Environment Setup

Complete guide for setting up a development environment for Orchestry, including local development, testing, and contribution workflows.

## Prerequisites

### System Requirements

- **Operating System**: Linux (Ubuntu 20.04+, CentOS 8+, or similar)
- **Python**: 3.9 or higher
- **Docker**: 20.10 or higher with Docker Compose
- **PostgreSQL**: 13 or higher (for development database)
- **Nginx**: 1.18 or higher (optional, for load balancer testing)
- **Git**: For version control

### Development Tools

```bash
# Essential development packages
sudo apt update
sudo apt install -y \
    python3.11 \
    python3.11-dev \
    python3.11-venv \
    postgresql-client \
    docker.io \
    docker-compose \
    nginx \
    git \
    curl \
    wget \
    build-essential \
    libpq-dev

# Start Docker service
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -a -G docker $USER
```

## Environment Setup

### 1. Clone the Repository

```bash
# Clone the ORCHESTRY repository
git clone https://github.com/admincodes7/Orchestry.git
cd Orchestry

# Create development branch
git checkout -b feature/your-feature-name
```

### 2. Python Environment

```bash
# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Upgrade pip and install development dependencies
pip install --upgrade pip
pip install -e .[dev]

# Install pre-commit hooks
pre-commit install
```

### 3. Development Dependencies

The `pyproject.toml` includes development dependencies:

```toml
[project.optional-dependencies]
dev = [
    # Testing
    "pytest>=7.0.0",
    "pytest-asyncio>=0.21.0",
    "pytest-cov>=4.0.0",
    "pytest-mock>=3.10.0",
    
    # Code quality
    "black>=23.0.0",
    "isort>=5.12.0",
    "flake8>=6.0.0",
    "mypy>=1.0.0",
    "pre-commit>=3.0.0",
    
    # Documentation
    "mkdocs>=1.4.0",
    "mkdocs-material>=9.0.0",
    "mkdocstrings[python]>=0.20.0",
    
    # Development utilities
    "ipython>=8.0.0",
    "debugpy>=1.6.0",
    "httpx>=0.24.0",
    "factory-boy>=3.2.0"
]
```

### 4. Database Setup

```bash
# Start PostgreSQL with Docker
docker run -d \
    --name orchestry-postgres \
    -e POSTGRES_DB=orchestry_dev \
    -e POSTGRES_USER=orchestry \
    -e POSTGRES_PASSWORD=development_password \
    -p 5432:5432 \
    postgres:15

# Wait for database to be ready
sleep 10

# Initialize database schema
python -m cli.main db init --connection-string "postgresql://orchestry:development_password@localhost:5432/orchestry_dev"
```

### 5. Configuration

Create development configuration file:

```bash
# Create config directory
mkdir -p ~/.config/orchestry

# Development configuration
cat > ~/.config/orchestry/development.yml << EOF
# Orchestry Development Configuration

database:
  primary:
    host: localhost
    port: 5432
    user: orchestry
    password: development_password
    database: orchestry_dev
  
  replica:
    enabled: false

docker:
  socket: "unix://var/run/docker.sock"
  network: "orchestry-dev"

controller:
  port: 8000
  host: "0.0.0.0"
  workers: 1
  debug: true
  
nginx:
  config_dir: "/tmp/orchestry-nginx"
  reload_command: "echo 'Nginx reload simulated'"

logging:
  level: DEBUG
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  
metrics:
  enabled: true
  retention_hours: 24

health_checks:
  default_timeout: 5
  default_interval: 30
  
scaling:
  default_min_replicas: 1
  default_max_replicas: 5
  evaluation_interval: 60
EOF
```

## Development Workflow

### Directory Structure

```
orchestry/
├── app_spec/          # Application specification models
├── cli/               # Command-line interface
├── controller/        # Main controller components
├── state/            # Database and state management
├── metrics/          # Metrics collection and export
├── configs/          # Configuration templates
├── tests/            # Test suite
├── docs/             # Documentation
├── examples/         # Example applications
├── scripts/          # Development scripts
└── docker/           # Docker configurations
```

### Code Organization

```python
# File naming conventions
controller/
├── __init__.py       # Package initialization
├── main.py          # Main entry point
├── api.py           # FastAPI REST API
├── manager.py       # Application management
├── scaler.py        # Auto-scaling logic
├── health.py        # Health monitoring
└── nginx.py         # Nginx integration

# Import organization (following isort configuration)
# 1. Standard library imports
import asyncio
import logging
from typing import Dict, List, Optional

# 2. Third-party imports
import aiohttp
import asyncpg
from fastapi import FastAPI

# 3. Local imports
from app_spec.models import AppSpec
from state.db import DatabaseManager
```

### Running Development Server

```bash
# Activate virtual environment
source venv/bin/activate

# Set development environment
export ORCHESTRY_ENV=development
export ORCHESTRY_CONFIG=~/.config/orchestry/development.yml

# Start the controller in development mode
python -m controller.main --reload --debug

# Or use the development script
./scripts/dev-server.sh
```

### Development Scripts

Create helpful development scripts in `scripts/`:

**`scripts/dev-server.sh`**:
```bash
#!/bin/bash
# Development server with auto-reload

set -e

# Activate virtual environment
source venv/bin/activate

# Set development environment variables
export ORCHESTRY_ENV=development
export ORCHESTRY_CONFIG=~/.config/orchestry/development.yml
export PYTHONPATH=$PWD:$PYTHONPATH

# Start development server
echo "Starting Orchestry development server..."
uvicorn controller.api:app \
    --reload \
    --host 0.0.0.0 \
    --port 8000 \
    --log-level debug \
    --reload-dir controller \
    --reload-dir app_spec \
    --reload-dir state
```

**`scripts/test.sh`**:
```bash
#!/bin/bash
# Run test suite with coverage

set -e

source venv/bin/activate

echo "Running tests with coverage..."
pytest \
    --cov=controller \
    --cov=app_spec \
    --cov=state \
    --cov=cli \
    --cov-report=html \
    --cov-report=term-missing \
    --cov-fail-under=80 \
    tests/

echo "Coverage report generated in htmlcov/"
```

**`scripts/lint.sh`**:
```bash
#!/bin/bash
# Code quality checks

set -e

source venv/bin/activate

echo "Running code formatting..."
black .
isort .

echo "Running linting..."
flake8 controller/ app_spec/ state/ cli/

echo "Running type checking..."
mypy controller/ app_spec/ state/ cli/

echo "All checks passed!"
```

## Testing

### Test Structure

```
tests/
├── conftest.py              # Pytest fixtures
├── unit/                   # Unit tests
│   ├── test_models.py
│   ├── test_manager.py
│   ├── test_scaler.py
│   └── test_health.py
├── integration/            # Integration tests
│   ├── test_api.py
│   ├── test_database.py
│   └── test_docker.py
├── e2e/                   # End-to-end tests
│   ├── test_deployment.py
│   └── test_scaling.py
└── fixtures/              # Test data
    ├── app_specs/
    └── responses/
```

### Test Configuration

**`tests/conftest.py`**:
```python
import asyncio
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

from controller.api import app
from controller.manager import AppManager
from state.db import DatabaseManager
from app_spec.models import AppSpec

@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()

@pytest_asyncio.fixture
async def db_manager():
    """Mock database manager."""
    manager = MagicMock(spec=DatabaseManager)
    
    # Mock async methods
    manager.get_application = AsyncMock()
    manager.list_applications = AsyncMock()
    manager.save_application = AsyncMock()
    manager.delete_application = AsyncMock()
    
    return manager

@pytest.fixture
def docker_client():
    """Mock Docker client."""
    client = MagicMock()
    
    # Mock containers
    client.containers.list = MagicMock(return_value=[])
    client.containers.run = MagicMock()
    client.containers.get = MagicMock()
    
    return client

@pytest_asyncio.fixture
async def app_manager(db_manager, docker_client):
    """App manager with mocked dependencies."""
    manager = AppManager(
        db=db_manager,
        docker_client=docker_client
    )
    return manager

@pytest.fixture
def test_client():
    """FastAPI test client."""
    return TestClient(app)

@pytest.fixture
def sample_app_spec():
    """Sample application specification."""
    return {
        "apiVersion": "orchestry.dev/v1",
        "kind": "Application",
        "metadata": {
            "name": "test-app",
            "labels": {
                "environment": "test"
            }
        },
        "spec": {
            "image": "nginx:alpine",
            "replicas": 2,
            "port": 80,
            "env": {},
            "resources": {
                "cpu": "100m",
                "memory": "128Mi"
            },
            "networking": {
                "external_port": 8080
            },
            "health_check": {
                "path": "/health",
                "interval": 30,
                "timeout": 5
            },
            "scaling": {
                "min_replicas": 1,
                "max_replicas": 5,
                "target_cpu": 70
            }
        }
    }

@pytest.fixture
def sample_instances():
    """Sample instance records."""
    return [
        {
            "id": 1,
            "app_name": "test-app",
            "container_id": "container1",
            "container_name": "test-app-0",
            "replica_index": 0,
            "ip": "172.17.0.2",
            "port": 80,
            "status": "running",
            "health_status": "healthy"
        },
        {
            "id": 2,
            "app_name": "test-app",
            "container_id": "container2",
            "container_name": "test-app-1",
            "replica_index": 1,
            "ip": "172.17.0.3",
            "port": 80,
            "status": "running",
            "health_status": "healthy"
        }
    ]
```

### Unit Tests

**`tests/unit/test_manager.py`**:
```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from controller.manager import AppManager
from app_spec.models import AppSpec

@pytest.mark.asyncio
async def test_deploy_application(app_manager, sample_app_spec):
    """Test application deployment."""
    # Setup
    app_spec = AppSpec.from_dict(sample_app_spec)
    app_manager.db.get_application.return_value = None
    app_manager.db.save_application = AsyncMock()
    
    with patch.object(app_manager, 'create_instance', new_callable=AsyncMock) as mock_create:
        mock_create.return_value = True
        
        # Execute
        result = await app_manager.deploy_application(app_spec)
        
        # Verify
        assert result is True
        app_manager.db.save_application.assert_called_once()
        assert mock_create.call_count == app_spec.spec.replicas

@pytest.mark.asyncio
async def test_scale_application(app_manager, sample_instances):
    """Test application scaling."""
    # Setup
    app_name = "test-app"
    target_replicas = 3
    
    app_manager.db.get_application.return_value = MagicMock(replicas=2)
    app_manager.db.list_instances.return_value = sample_instances
    
    with patch.object(app_manager, 'create_instance', new_callable=AsyncMock) as mock_create:
        mock_create.return_value = True
        
        # Execute
        result = await app_manager.scale_application(app_name, target_replicas)
        
        # Verify
        assert result is True
        mock_create.assert_called_once()

@pytest.mark.asyncio
async def test_remove_application(app_manager, sample_instances):
    """Test application removal."""
    # Setup
    app_name = "test-app"
    app_manager.db.list_instances.return_value = sample_instances
    
    with patch.object(app_manager, 'stop_container', new_callable=AsyncMock) as mock_stop:
        mock_stop.return_value = True
        app_manager.db.delete_application = AsyncMock()
        
        # Execute
        result = await app_manager.remove_application(app_name)
        
        # Verify
        assert result is True
        assert mock_stop.call_count == len(sample_instances)
        app_manager.db.delete_application.assert_called_once_with(app_name)
```

### Integration Tests

**`tests/integration/test_api.py`**:
```python
import pytest
from unittest.mock import AsyncMock, patch

def test_list_applications(test_client):
    """Test listing applications endpoint."""
    with patch('controller.api.app_manager') as mock_manager:
        mock_manager.list_applications = AsyncMock(return_value=[])
        
        response = test_client.get("/api/v1/applications")
        
        assert response.status_code == 200
        assert response.json() == {"applications": []}

def test_deploy_application(test_client, sample_app_spec):
    """Test deploy application endpoint."""
    with patch('controller.api.app_manager') as mock_manager:
        mock_manager.deploy_application = AsyncMock(return_value=True)
        
        response = test_client.post(
            "/api/v1/applications",
            json=sample_app_spec
        )
        
        assert response.status_code == 201
        assert "name" in response.json()

def test_get_application_status(test_client):
    """Test get application status endpoint."""
    app_name = "test-app"
    
    with patch('controller.api.app_manager') as mock_manager:
        mock_manager.get_application_status = AsyncMock(return_value={
            "name": app_name,
            "status": "running",
            "replicas": 2,
            "healthy_instances": 2
        })
        
        response = test_client.get(f"/api/v1/applications/{app_name}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == app_name
        assert data["status"] == "running"
```

### End-to-End Tests

**`tests/e2e/test_deployment.py`**:
```python
import pytest
import asyncio
import aiohttp
from unittest.mock import patch

@pytest.mark.asyncio
@pytest.mark.e2e
async def test_full_deployment_workflow():
    """Test complete deployment workflow."""
    app_spec = {
        "apiVersion": "orchestry.dev/v1",
        "kind": "Application",
        "metadata": {"name": "e2e-test-app"},
        "spec": {
            "image": "nginx:alpine",
            "replicas": 1,
            "port": 80,
            "health_check": {"path": "/", "interval": 10}
        }
    }
    
    # Deploy application
    async with aiohttp.ClientSession() as session:
        # 1. Deploy application
        async with session.post(
            "http://localhost:8000/api/v1/applications",
            json=app_spec
        ) as response:
            assert response.status == 201
            deployment_data = await response.json()
            assert deployment_data["name"] == "e2e-test-app"
        
        # 2. Wait for deployment to complete
        await asyncio.sleep(30)
        
        # 3. Check application status
        async with session.get(
            "http://localhost:8000/api/v1/applications/e2e-test-app"
        ) as response:
            assert response.status == 200
            status_data = await response.json()
            assert status_data["status"] == "running"
            assert status_data["healthy_instances"] >= 1
        
        # 4. Test scaling
        async with session.put(
            "http://localhost:8000/api/v1/applications/e2e-test-app/scale",
            json={"replicas": 2}
        ) as response:
            assert response.status == 200
        
        # 5. Wait for scaling to complete
        await asyncio.sleep(20)
        
        # 6. Verify scaling
        async with session.get(
            "http://localhost:8000/api/v1/applications/e2e-test-app"
        ) as response:
            assert response.status == 200
            status_data = await response.json()
            assert status_data["replicas"] == 2
        
        # 7. Clean up
        async with session.delete(
            "http://localhost:8000/api/v1/applications/e2e-test-app"
        ) as response:
            assert response.status == 204
```

## Debugging

### VS Code Configuration

Create `.vscode/launch.json`:

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Orchestry Controller",
            "type": "python",
            "request": "launch",
            "module": "controller.main",
            "args": ["--debug"],
            "console": "integratedTerminal",
            "env": {
                "ORCHESTRY_ENV": "development",
                "ORCHESTRY_CONFIG": "${env:HOME}/.config/orchestry/development.yml",
                "PYTHONPATH": "${workspaceFolder}"
            },
            "cwd": "${workspaceFolder}",
            "justMyCode": false
        },
        {
            "name": "CLI Tool",
            "type": "python",
            "request": "launch",
            "module": "cli.main",
            "args": ["--help"],
            "console": "integratedTerminal",
            "env": {
                "ORCHESTRY_ENV": "development",
                "ORCHESTRY_CONFIG": "${env:HOME}/.config/orchestry/development.yml"
            },
            "cwd": "${workspaceFolder}"
        },
        {
            "name": "Pytest Current File",
            "type": "python",
            "request": "launch",
            "module": "pytest",
            "args": ["${file}", "-v"],
            "console": "integratedTerminal",
            "cwd": "${workspaceFolder}"
        }
    ]
}
```

### Logging Configuration

**Development logging setup**:

```python
import logging
import sys

def setup_development_logging():
    """Configure logging for development."""
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
    )
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)
    
    # File handler
    file_handler = logging.FileHandler('orchestry-dev.log')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    
    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    
    # Third-party loggers
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('docker').setLevel(logging.INFO)
    logging.getLogger('asyncpg').setLevel(logging.INFO)
```

### Remote Debugging

For remote debugging with debugpy:

```python
import debugpy

# Enable remote debugging
debugpy.listen(("0.0.0.0", 5678))
print("Waiting for debugger to attach...")
debugpy.wait_for_client()
print("Debugger attached!")
```

## Contributing

### Code Style

Orchestry follows these code style guidelines:

1. **PEP 8** compliance with line length of 100 characters
2. **Black** for code formatting
3. **isort** for import sorting
4. **Type hints** for all public functions
5. **Docstrings** in Google style

### Pre-commit Configuration

**`.pre-commit-config.yaml`**:

```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.4.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
      - id: check-merge-conflict

  - repo: https://github.com/psf/black
    rev: 23.3.0
    hooks:
      - id: black
        language_version: python3.11

  - repo: https://github.com/pycqa/isort
    rev: 5.12.0
    hooks:
      - id: isort

  - repo: https://github.com/pycqa/flake8
    rev: 6.0.0
    hooks:
      - id: flake8
        additional_dependencies: [flake8-docstrings]

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.3.0
    hooks:
      - id: mypy
        additional_dependencies: [types-all]
```

### Pull Request Process

1. **Fork and Branch**: Create a feature branch from `main`
2. **Development**: Implement changes following code style guidelines
3. **Testing**: Ensure all tests pass and add tests for new functionality
4. **Documentation**: Update documentation for new features
5. **Pull Request**: Submit PR with clear description and link to issues

### Commit Message Format

Follow conventional commit format:

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

Examples:
```
feat(scaler): add memory-based scaling algorithm
fix(health): handle timeout errors gracefully
docs(api): update deployment endpoint documentation
```

## Performance Profiling

### Memory Profiling

```bash
# Install memory profiler
pip install memory-profiler

# Profile memory usage
python -m memory_profiler controller/main.py
```

### CPU Profiling

```python
import cProfile
import pstats

# Profile application startup
profiler = cProfile.Profile()
profiler.enable()

# Your code here
await app_manager.initialize()

profiler.disable()
stats = pstats.Stats(profiler)
stats.sort_stats('cumulative').print_stats(20)
```

### Async Profiling

```bash
# Install async profiler
pip install py-spy

# Profile running application
py-spy top --pid <process_id>
py-spy record -o profile.svg --pid <process_id>
```

---

**Next**: Learn about [Extensions and Plugins](extensions.md) for extending ORCHESTRY functionality.