"""
FastAPI-based Admin API for the AutoServe controller.
Provides endpoints for app management, scaling, and monitoring.
"""

import logging
import threading
import time
import os
from typing import Dict, List, Optional, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .manager import AppManager
from .state import StateStore  
from .nginx import DockerNginxManager
from .scaler import AutoScaler, ScalingPolicy, ScalingMetrics
from .health import HealthChecker

logger = logging.getLogger(__name__)

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

# Global components - initialized when starting the API
app_manager: Optional[AppManager] = None
state_store: Optional[StateStore] = None
nginx_manager: Optional[DockerNginxManager] = None
auto_scaler: Optional[AutoScaler] = None
health_checker: Optional[HealthChecker] = None

# Background monitoring task
monitoring_task: Optional[threading.Thread] = None
monitoring_active = False

# FastAPI app
app = FastAPI(
    title="AutoServe Controller API",
    description="Docker-based autoscaling controller API",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    """Initialize all components when the API starts."""
    global app_manager, state_store, nginx_manager, auto_scaler, health_checker
    global monitoring_task, monitoring_active
    
    try:
        # Initialize components with environment-based configuration
        db_path = os.getenv("AUTOSERVE_DB_PATH", "autoscaler.db")
        state_store = StateStore(db_path)
        nginx_manager = DockerNginxManager()
        auto_scaler = AutoScaler()
        health_checker = HealthChecker()
        app_manager = AppManager(state_store, nginx_manager)
        
        # Start health checker
        await health_checker.start()
        
        # Start background monitoring
        monitoring_active = True
        monitoring_task = threading.Thread(target=background_monitoring, daemon=True)
        monitoring_task.start()
        
        # Clean up orphaned containers
        app_manager.cleanup_orphaned_containers()
        
        logger.info("AutoServe Controller API started successfully")
        
    except Exception as e:
        logger.error(f"Failed to start controller: {e}")
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """Clean up resources when shutting down."""
    global monitoring_active, health_checker
    
    monitoring_active = False
    
    if health_checker:
        await health_checker.stop()
    
    if state_store:
        state_store.close()
    
    logger.info("AutoServe Controller API shut down")

def background_monitoring():
    """Background thread for monitoring and autoscaling."""
    logger.info("Started background monitoring thread")
    
    while monitoring_active:
        try:
            if not app_manager or not auto_scaler:
                time.sleep(5)
                continue
            
            # Get list of all apps
            apps = state_store.list_apps()
            
            for app_info in apps:
                app_name = app_info["name"]
                
                # Get current instances
                if app_name not in app_manager.instances:
                    continue
                
                instances = app_manager.instances[app_name]
                if not instances:
                    continue
                
                # Update container stats
                app_manager._update_container_stats(app_name)
                
                # Collect metrics for scaling
                healthy_count = sum(1 for inst in instances if inst.state == "ready")
                total_cpu = sum(inst.cpu_percent for inst in instances) / len(instances) if instances else 0
                total_memory = sum(inst.memory_percent for inst in instances) / len(instances) if instances else 0
                
                # Create metrics object (simplified for now)
                metrics = ScalingMetrics(
                    rps=0,  # Would come from nginx stats or app metrics
                    p95_latency_ms=0,  # Would come from app metrics
                    active_connections=0,  # Would come from nginx stats
                    cpu_percent=total_cpu,
                    memory_percent=total_memory,
                    healthy_replicas=healthy_count,
                    total_replicas=len(instances)
                )
                
                # Add metrics to scaler
                auto_scaler.add_metrics(app_name, metrics)
                
                # Evaluate scaling decision
                decision = auto_scaler.evaluate_scaling(app_name, len(instances))
                
                if decision.should_scale:
                    logger.info(f"Scaling {app_name}: {decision.reason}")
                    
                    # Perform scaling
                    result = app_manager.scale(app_name, decision.target_replicas)
                    
                    if result.get("status") == "scaled":
                        # Record scaling action
                        auto_scaler.record_scaling_action(app_name, decision.target_replicas)
                        
                        # Log to state store
                        state_store.log_scaling_action(
                            app_name,
                            decision.current_replicas,
                            decision.target_replicas,
                            decision.reason,
                            decision.triggered_by,
                            decision.metrics.__dict__ if decision.metrics else None
                        )
                        
                        # Log event
                        state_store.log_event(app_name, "scaled", {
                            "old_replicas": decision.current_replicas,
                            "new_replicas": decision.target_replicas,
                            "reason": decision.reason
                        })
            
            # Sleep before next monitoring cycle
            time.sleep(10)
            
        except Exception as e:
            logger.error(f"Error in background monitoring: {e}")
            time.sleep(30)  # Back off on errors

# API Endpoints

@app.post("/apps/register", response_model=AppRegistrationResponse)
async def register_app(app_spec: AppSpec):
    """Register a new application."""
    try:
        # Convert AppSpec to dict for manager
        spec_dict = app_spec.dict() if hasattr(app_spec, 'dict') else app_spec
        result = app_manager.register(spec_dict)
        
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        
        # Get app name from metadata
        app_name = spec_dict.get("metadata", {}).get("name")
        if not app_name:
            raise HTTPException(status_code=400, detail="App name is required in metadata")
        
        # Set up default scaling policy from the scaling section
        scaling_config = spec_dict.get("scaling", {})
        
        policy = ScalingPolicy(
            min_replicas=scaling_config.get("minReplicas", 1),
            max_replicas=scaling_config.get("maxReplicas", 5),
            target_rps_per_replica=scaling_config.get("targetRPSPerReplica", 50),
            max_p95_latency_ms=scaling_config.get("maxP95LatencyMs", 250),
            scale_out_threshold_pct=scaling_config.get("scaleOutThresholdPct", 80),
            scale_in_threshold_pct=scaling_config.get("scaleInThresholdPct", 30),
            window_seconds=scaling_config.get("windowSeconds", 60),
            cooldown_seconds=scaling_config.get("cooldownSeconds", 300)
        )
        
        auto_scaler.set_policy(app_name, policy)
        
        # Log event
        state_store.log_event(app_name, "registered", {"spec": spec_dict.get("spec", {})})
        
        return AppRegistrationResponse(
            status="registered",
            app=app_name,
            message="Application registered successfully"
        )
        
    except Exception as e:
        logger.error(f"Failed to register app: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/apps/{name}/up")
async def app_up(name: str):
    """Start an application."""
    try:
        result = app_manager.start(name)
        
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        
        # Log event
        state_store.log_event(name, "started", result)
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to start app {name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/apps/{name}/down")
async def app_down(name: str):
    """Stop an application."""
    try:
        result = app_manager.stop(name)
        
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        
        # Log event
        state_store.log_event(name, "stopped", result)
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to stop app {name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/apps/{name}/status", response_model=AppStatusResponse)
async def app_status(name: str):
    """Get the status of an application."""
    try:
        result = app_manager.status(name)
        
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        
        return AppStatusResponse(**result)
        
    except Exception as e:
        logger.error(f"Failed to get status for app {name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/apps/{name}/scale")
async def scale_app(name: str, scale_request: ScaleRequest):
    """Manually scale an application."""
    try:
        result = app_manager.scale(name, scale_request.replicas)
        
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        
        # Log scaling action
        current_replicas = len(app_manager.instances.get(name, []))
        state_store.log_scaling_action(
            name, current_replicas, scale_request.replicas,
            "Manual scaling", ["manual"]
        )
        
        # Log event
        state_store.log_event(name, "manual_scale", {
            "old_replicas": current_replicas,
            "new_replicas": scale_request.replicas
        })
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to scale app {name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/apps/{name}/policy")
async def update_policy(name: str, policy_request: PolicyRequest):
    """Update scaling policy for an application."""
    try:
        policy_data = policy_request.policy
        
        policy = ScalingPolicy(
            min_replicas=policy_data.get("minReplicas", 1),
            max_replicas=policy_data.get("maxReplicas", 5),
            target_rps_per_replica=policy_data.get("targetRPSPerReplica", 50),
            max_p95_latency_ms=policy_data.get("maxP95LatencyMs", 250),
            scale_out_threshold_pct=policy_data.get("scaleOutThresholdPct", 80),
            scale_in_threshold_pct=policy_data.get("scaleInThresholdPct", 30),
            window_seconds=policy_data.get("windowSeconds", 20),
            cooldown_seconds=policy_data.get("cooldownSeconds", 30)
        )
        
        auto_scaler.set_policy(name, policy)
        
        # Log event
        state_store.log_event(name, "policy_updated", policy_data)
        
        return {"status": "updated", "app": name, "policy": policy_data}
        
    except Exception as e:
        logger.error(f"Failed to update policy for app {name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/apps")
async def list_apps():
    """List all registered applications."""
    try:
        apps = state_store.list_apps()
        
        # Add runtime status
        for app in apps:
            status_result = app_manager.status(app["name"])
            app["status"] = status_result.get("status", "unknown")
            app["replicas"] = status_result.get("replicas", 0)
            app["ready_replicas"] = status_result.get("ready_replicas", 0)
        
        return {"apps": apps}
        
    except Exception as e:
        logger.error(f"Failed to list apps: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/apps/{name}/logs")
async def get_app_logs(name: str, lines: int = 100):
    """Get logs for an application."""
    try:
        if name not in app_manager.instances:
            raise HTTPException(status_code=404, detail="App not found or not running")
        
        # This would collect logs from all containers
        # For now, return a placeholder
        return {
            "app": name,
            "logs": [
                {"timestamp": time.time(), "container": "placeholder", "message": "Log collection not implemented"}
            ]
        }
        
    except Exception as e:
        logger.error(f"Failed to get logs for app {name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/apps/{name}/metrics")
async def get_app_metrics(name: str):
    """Get metrics for an application."""
    try:
        metrics_summary = auto_scaler.get_metrics_summary(name)
        scaling_history = state_store.get_scaling_history(name, limit=10)
        
        return {
            "app": name,
            "metrics": metrics_summary,
            "scaling_history": scaling_history
        }
        
    except Exception as e:
        logger.error(f"Failed to get metrics for app {name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/metrics")
async def get_system_metrics():
    """Get system-wide metrics for monitoring."""
    try:
        # Collect metrics from all components
        all_apps = state_store.list_apps()
        total_apps = len(all_apps)
        running_apps = 0
        total_instances = 0
        healthy_instances = 0
        
        for app in all_apps:
            app_name = app["name"]
            if app_name in app_manager.instances:
                instances = app_manager.instances[app_name]
                if instances:
                    running_apps += 1
                    total_instances += len(instances)
                    healthy_instances += sum(1 for inst in instances if inst.state == "ready")
        
        # Get nginx status
        nginx_status = nginx_manager.get_nginx_status()
        
        # Get health check summary
        health_summary = health_checker.get_health_summary()
        
        return {
            "timestamp": time.time(),
            "apps": {
                "total": total_apps,
                "running": running_apps
            },
            "instances": {
                "total": total_instances,
                "healthy": healthy_instances,
                "unhealthy": total_instances - healthy_instances
            },
            "nginx": nginx_status,
            "health_checks": health_summary
        }
        
    except Exception as e:
        logger.error(f"Failed to get system metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/events")
async def get_events(app: Optional[str] = None, limit: int = 100):
    """Get recent events."""
    try:
        events = state_store.get_events(app, limit)
        return {"events": events}
        
    except Exception as e:
        logger.error(f"Failed to get events: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "version": "1.0.0"
    }

# Add this to run the server
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

