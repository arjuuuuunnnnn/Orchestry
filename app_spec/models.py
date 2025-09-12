"""
Pydantic dataclasses for AutoServe application specifications.
Defines the schema for YAML/JSON app registration format.
"""

from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field, validator
from enum import Enum

class AppKind(str, Enum):
    """Supported application kinds."""
    APP = "App"
    WORKER = "Worker"  # Future: background jobs

class RestartPolicy(str, Enum):
    """Container restart policies."""
    ALWAYS = "Always"
    ON_FAILURE = "OnFailure" 
    NEVER = "Never"

class Protocol(str, Enum):
    """Supported protocols."""
    HTTP = "HTTP"
    TCP = "TCP"

class EnvVarSource(str, Enum):
    """Environment variable sources."""
    VALUE = "value"
    SDK = "sdk"  # Provided by AutoServe
    SECRET = "secret"  # Future: secret management

class ScalingMetric(str, Enum):
    """Scaling metrics."""
    CPU = "cpu"
    MEMORY = "memory"
    RPS = "rps"
    LATENCY = "latency"
    CONNECTIONS = "connections"

# Base models

class EnvVar(BaseModel):
    """Environment variable specification."""
    name: str = Field(..., description="Environment variable name")
    value: Optional[str] = Field(None, description="Static value")
    valueFrom: Optional[EnvVarSource] = Field(None, description="Dynamic value source")
    
    @validator('value', 'valueFrom')
    def value_or_value_from(cls, v, values):
        if not v and not values.get('valueFrom'):
            raise ValueError('Either value or valueFrom must be specified')
        if v and values.get('valueFrom'):
            raise ValueError('Cannot specify both value and valueFrom')
        return v

class ResourceRequirements(BaseModel):
    """Container resource requirements."""
    cpu: Optional[str] = Field("100m", description="CPU limit (e.g., '100m', '0.5')")
    memory: Optional[str] = Field("128Mi", description="Memory limit (e.g., '128Mi', '1Gi')")
    
class Port(BaseModel):
    """Container port specification."""
    containerPort: int = Field(..., description="Port inside the container")
    protocol: Protocol = Field(Protocol.HTTP, description="Port protocol")
    name: Optional[str] = Field(None, description="Port name")

class HealthCheck(BaseModel):
    """Health check configuration."""
    path: str = Field("/health", description="Health check endpoint path")
    port: Optional[int] = Field(None, description="Health check port (defaults to container port)")
    initialDelaySeconds: int = Field(30, description="Delay before first health check")
    periodSeconds: int = Field(10, description="Interval between health checks")
    timeoutSeconds: int = Field(5, description="Health check timeout")
    failureThreshold: int = Field(3, description="Failures before marking unhealthy")
    successThreshold: int = Field(1, description="Successes before marking healthy")

class ScalingPolicy(BaseModel):
    """Autoscaling policy configuration."""
    minReplicas: int = Field(1, ge=0, le=100, description="Minimum number of replicas")
    maxReplicas: int = Field(5, ge=1, le=100, description="Maximum number of replicas")
    targetCPUUtilizationPercentage: Optional[int] = Field(70, ge=1, le=100)
    targetMemoryUtilizationPercentage: Optional[int] = Field(75, ge=1, le=100)
    targetRPSPerReplica: Optional[int] = Field(50, ge=1, description="Target RPS per replica")
    maxP95LatencyMs: Optional[int] = Field(200, ge=1, description="Max p95 latency in ms")
    scaleOutThresholdPct: int = Field(80, ge=1, le=100, description="Threshold to scale out")
    scaleInThresholdPct: int = Field(30, ge=1, le=100, description="Threshold to scale in")
    windowSeconds: int = Field(60, ge=10, description="Evaluation window in seconds")
    cooldownSeconds: int = Field(300, ge=30, description="Cooldown between scaling events")
    
    @validator('maxReplicas')
    def max_greater_than_min(cls, v, values):
        if 'minReplicas' in values and v < values['minReplicas']:
            raise ValueError('maxReplicas must be >= minReplicas')
        return v
        
    @validator('scaleOutThresholdPct')  
    def scale_out_greater_than_scale_in(cls, v, values):
        if 'scaleInThresholdPct' in values and v <= values['scaleInThresholdPct']:
            raise ValueError('scaleOutThresholdPct must be > scaleInThresholdPct')
        return v

class TerminationConfig(BaseModel):
    """Graceful termination configuration."""
    drainSeconds: int = Field(30, ge=0, le=300, description="Time to drain connections")
    terminationGracePeriodSeconds: int = Field(30, ge=0, le=300, description="SIGTERM timeout")

class Metadata(BaseModel):
    """App metadata."""
    name: str = Field(..., description="Application name", regex=r'^[a-zA-Z0-9]([a-zA-Z0-9\-])*[a-zA-Z0-9]$')
    labels: Optional[Dict[str, str]] = Field(default_factory=dict, description="Key-value labels")
    annotations: Optional[Dict[str, str]] = Field(default_factory=dict, description="Key-value annotations")
    
    @validator('name')
    def validate_name(cls, v):
        if not v or len(v) > 63:
            raise ValueError('Name must be 1-63 characters')
        return v

class ContainerSpec(BaseModel):
    """Container specification."""
    image: str = Field(..., description="Docker image (with tag)")
    command: Optional[List[str]] = Field(None, description="Override container command")
    args: Optional[List[str]] = Field(None, description="Override container args")
    workingDir: Optional[str] = Field(None, description="Working directory")
    env: Optional[List[EnvVar]] = Field(default_factory=list, description="Environment variables")
    resources: Optional[ResourceRequirements] = Field(default_factory=ResourceRequirements)
    ports: List[Port] = Field(..., description="Container ports")
    
    @validator('image')
    def validate_image(cls, v):
        if ':' not in v:
            raise ValueError('Image must include a tag (e.g., myapp:latest)')
        return v
        
    @validator('ports')
    def validate_ports(cls, v):
        if not v:
            raise ValueError('At least one port must be specified')
        
        ports = [p.containerPort for p in v]
        if len(ports) != len(set(ports)):
            raise ValueError('Port numbers must be unique')
            
        return v

class AppSpec(BaseModel):
    """Complete application specification."""
    apiVersion: str = Field("v1", description="API version")
    kind: AppKind = Field(AppKind.APP, description="Application kind")
    metadata: Metadata = Field(..., description="Application metadata")
    spec: ContainerSpec = Field(..., description="Container specification")
    
    # Optional configurations
    scaling: Optional[ScalingPolicy] = Field(default_factory=ScalingPolicy, description="Scaling policy")
    healthCheck: Optional[HealthCheck] = Field(default_factory=HealthCheck, description="Health check config")
    termination: Optional[TerminationConfig] = Field(default_factory=TerminationConfig, description="Termination config")
    restartPolicy: RestartPolicy = Field(RestartPolicy.ALWAYS, description="Restart policy")
    
    @validator('apiVersion')
    def validate_api_version(cls, v):
        if v not in ['v1']:
            raise ValueError('Unsupported API version')
        return v

# Utility classes for API responses

class AppStatus(BaseModel):
    """Application status response."""
    name: str
    status: str  # registered, starting, running, scaling, stopping, stopped, error
    replicas: int
    readyReplicas: int
    availableReplicas: int
    conditions: List[Dict[str, Any]] = Field(default_factory=list)
    lastScalingEvent: Optional[Dict[str, Any]] = None

class ContainerStatus(BaseModel):
    """Container instance status."""
    containerId: str
    image: str
    state: str  # pending, running, terminated
    ready: bool
    restartCount: int
    lastState: Optional[Dict[str, str]] = None
    
class AppStatusDetail(BaseModel):
    """Detailed application status."""
    metadata: Metadata
    spec: AppSpec
    status: AppStatus
    containers: List[ContainerStatus] = Field(default_factory=list)
    events: List[Dict[str, Any]] = Field(default_factory=list)

class ScalingEvent(BaseModel):
    """Scaling event record."""
    timestamp: float
    fromReplicas: int
    toReplicas: int
    reason: str
    triggeredBy: List[str] = Field(default_factory=list)
    metrics: Optional[Dict[str, float]] = None

# Configuration validation helpers

def validate_app_spec(spec_dict: Dict[str, Any]) -> AppSpec:
    """
    Validate and parse an application specification.
    
    Args:
        spec_dict: Dictionary containing the app specification
        
    Returns:
        Validated AppSpec object
        
    Raises:
        ValueError: If the specification is invalid
    """
    try:
        return AppSpec(**spec_dict)
    except Exception as e:
        raise ValueError(f"Invalid application specification: {e}")

def get_default_spec(app_name: str, image: str) -> Dict[str, Any]:
    """
    Generate a default application specification.
    
    Args:
        app_name: Name of the application
        image: Docker image to use
        
    Returns:
        Default specification dictionary
    """
    return {
        "apiVersion": "v1",
        "kind": "App",
        "metadata": {
            "name": app_name,
            "labels": {
                "app": app_name,
                "managed-by": "autoserve"
            }
        },
        "spec": {
            "image": image,
            "ports": [
                {
                    "containerPort": 8080,
                    "protocol": "HTTP",
                    "name": "http"
                }
            ],
            "env": [
                {
                    "name": "PORT",
                    "value": "8080"
                }
            ],
            "resources": {
                "cpu": "100m",
                "memory": "128Mi"
            }
        },
        "scaling": {
            "minReplicas": 1,
            "maxReplicas": 3,
            "targetRPSPerReplica": 50,
            "maxP95LatencyMs": 200
        },
        "healthCheck": {
            "path": "/health",
            "periodSeconds": 10,
            "timeoutSeconds": 5,
            "failureThreshold": 3
        }
    }

def get_example_specs() -> Dict[str, Dict[str, Any]]:
    """Get example application specifications for different use cases."""
    
    return {
        "simple-web-app": {
            "apiVersion": "v1",
            "kind": "App",
            "metadata": {
                "name": "my-web-app",
                "labels": {
                    "app": "my-web-app",
                    "tier": "frontend"
                }
            },
            "spec": {
                "image": "nginx:alpine",
                "ports": [
                    {"containerPort": 80, "protocol": "HTTP"}
                ],
                "resources": {
                    "cpu": "50m",
                    "memory": "64Mi"
                }
            }
        },
        
        "node-api": {
            "apiVersion": "v1", 
            "kind": "App",
            "metadata": {
                "name": "node-api",
                "labels": {
                    "app": "node-api",
                    "tier": "backend",
                    "language": "nodejs"
                }
            },
            "spec": {
                "image": "node:18-alpine",
                "command": ["node"],
                "args": ["server.js"],
                "workingDir": "/app",
                "ports": [
                    {"containerPort": 3000, "protocol": "HTTP", "name": "api"}
                ],
                "env": [
                    {"name": "NODE_ENV", "value": "production"},
                    {"name": "PORT", "value": "3000"}
                ],
                "resources": {
                    "cpu": "200m",
                    "memory": "256Mi"
                }
            },
            "scaling": {
                "minReplicas": 2,
                "maxReplicas": 10,
                "targetRPSPerReplica": 100,
                "maxP95LatencyMs": 150,
                "targetCPUUtilizationPercentage": 60
            },
            "healthCheck": {
                "path": "/api/health",
                "port": 3000,
                "initialDelaySeconds": 15,
                "periodSeconds": 5,
                "timeoutSeconds": 3
            }
        },

        "python-ml-service": {
            "apiVersion": "v1",
            "kind": "App", 
            "metadata": {
                "name": "ml-inference",
                "labels": {
                    "app": "ml-inference",
                    "tier": "ml",
                    "language": "python"
                }
            },
            "spec": {
                "image": "python:3.11-slim",
                "command": ["python"],
                "args": ["-m", "uvicorn", "app:app", "--host", "0.0.0.0"],
                "ports": [
                    {"containerPort": 8000, "protocol": "HTTP"}
                ],
                "env": [
                    {"name": "MODEL_PATH", "value": "/models/model.pkl"},
                    {"name": "WORKERS", "value": "2"}
                ],
                "resources": {
                    "cpu": "500m",
                    "memory": "1Gi"
                }
            },
            "scaling": {
                "minReplicas": 1,
                "maxReplicas": 5,
                "targetRPSPerReplica": 20,
                "maxP95LatencyMs": 500,
                "targetCPUUtilizationPercentage": 70,
                "targetMemoryUtilizationPercentage": 80
            },
            "healthCheck": {
                "path": "/health",
                "initialDelaySeconds": 30,
                "periodSeconds": 15,
                "timeoutSeconds": 10
            },
            "termination": {
                "drainSeconds": 60,
                "terminationGracePeriodSeconds": 45
            }
        }
    }
