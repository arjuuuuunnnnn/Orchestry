from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any

class AppSpec(BaseModel):
    apiVersion: str = "v1"
    kind: str = "App"
    metadata: Dict[str, Any]  # Changed to Any to accept nested dicts
    spec: Dict[str, Any]      # Changed to Any for flexibility
    scaling: Optional[Dict[str, Any]] = None
    healthCheck: Optional[Dict[str, Any]] = None

class ScaleRequest(BaseModel):
    replicas: int = Field(..., ge=0, le=100)

class PolicyRequest(BaseModel):
    policy: Dict

class SimulatedMetricsRequest(BaseModel):
    rps: float = 0
    p95LatencyMs: float = 0
    activeConnections: int = 0
    cpuPercent: float = 0
    memoryPercent: float = 0
    healthyReplicas: int | None = None
    evaluate: bool = True  # whether to immediately evaluate and act on scaling

class AppRegistrationResponse(BaseModel):
    status: str
    app: str
    message: Optional[str] = None

class AppStatusResponse(BaseModel):
    app: str
    status: str
    replicas: int
    ready_replicas: int
    instances: List[Dict]
    mode: str = "auto"