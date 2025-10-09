import logging
import time
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from functools import wraps
from dotenv import load_dotenv

from .scaler import ScalingMetrics, ScalingPolicy
from controller.utils.models import (
    AppSpec,
    ScaleRequest,
    PolicyRequest,
    SimulatedMetricsRequest,
    AppRegistrationResponse,
    AppStatusResponse
)
from controller.utils import lifecycle

load_dotenv()

logger = logging.getLogger(__name__)

def leader_required(f):
    """Decorator to ensure only the leader can execute certain operations"""
    @wraps(f)
    async def decorated_function(*args, **kwargs):
        cluster_controller = get_cluster_controller()
        if cluster_controller and not cluster_controller.is_leader:
            leader_info = cluster_controller.get_leader_info()
            if leader_info:
                # Instead of redirecting, return 503 to let load balancer try next controller
                raise HTTPException(
                    status_code=503, 
                    detail=f"Not the leader. Leader is: {leader_info.get('leader_id', 'unknown')}",
                    headers={"X-Current-Leader": leader_info.get('leader_id', 'unknown')}
                )
            else:
                raise HTTPException(
                    status_code=503, 
                    detail="No leader elected, cluster not ready"
                )
        return await f(*args, **kwargs)
    return decorated_function

# FastAPI app
app = FastAPI(
    title="Orchestry Controller API",
    description="Docker-based autoscaling controller API",
    version="1.0.0"
)

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
    await lifecycle.startup_event()

@app.on_event("shutdown")
async def shutdown_event():
    """Clean up resources when shutting down."""
    await lifecycle.shutdown_event()

def get_app_manager():
    return lifecycle.get_app_manager()

def get_state_store():
    return lifecycle.get_state_store()

def get_nginx_manager():
    return lifecycle.get_nginx_manager()

def get_auto_scaler():
    return lifecycle.get_auto_scaler()

def get_health_checker():
    return lifecycle.get_health_checker()

def get_cluster_controller():
    return lifecycle.get_cluster_controller()

# API Endpoints

@app.post("/apps/register", response_model=AppRegistrationResponse)
@leader_required
async def register_app(app_spec: AppSpec):
    """Register a new application."""
    try:
        # Convert AppSpec to dict for manager
        spec_dict = app_spec.dict() if hasattr(app_spec, 'dict') else app_spec
        result = get_app_manager().register(spec_dict)
        
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
        
        get_auto_scaler().set_policy(app_name, policy)
        
        # Log event
        get_state_store().log_event(app_name, "registered", {"spec": spec_dict.get("spec", {})})
        
        return AppRegistrationResponse(
            status="registered",
            app=app_name,
            message="Application registered successfully"
        )
        
    except Exception as e:
        logger.error(f"Failed to register app: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/apps/{name}/up")
@leader_required
async def start_app(name: str):
    """Start an application."""
    try:
        result = get_app_manager().start(name)
        
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        
        # Log event
        get_state_store().log_event(name, "started", result)
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to start app {name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/apps/{name}/down")
@leader_required
async def stop_app(name: str):
    """Stop an application."""
    try:
        result = get_app_manager().stop(name)
        
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        
        # Log event
        get_state_store().log_event(name, "stopped", result)
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to stop app {name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/apps/{name}/status", response_model=AppStatusResponse)
async def app_status(name: str):
    """Get the status of an application."""
    try:
        result = get_app_manager().status(name)
        
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        
        # Get app mode from database
        app_record = get_state_store().get_app(name)
        app_mode = app_record.mode if app_record else "auto"
        
        # Add mode to the result
        result["mode"] = app_mode
        
        return AppStatusResponse(**result)
        
    except Exception as e:
        logger.error(f"Failed to get status for app {name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/apps/{name}/scale")
@leader_required
async def scale_app(name: str, scale_request: ScaleRequest):
    """Manually scale an application."""
    try:
        result = get_app_manager().scale(name, scale_request.replicas)
        
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        
        # Log scaling action
        current_replicas = len(get_app_manager().instances.get(name, []))
        get_state_store().log_scaling_action(
            name, current_replicas, scale_request.replicas,
            "Manual scaling", ["manual"]
        )
        
        # Log event
        get_state_store().log_event(name, "manual_scale", {
            "old_replicas": current_replicas,
            "new_replicas": scale_request.replicas
        })
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to scale app {name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/apps/{name}/policy")
@leader_required
async def set_scaling_policy(name: str, policy_request: PolicyRequest):
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
        
        get_auto_scaler().set_policy(name, policy)
        
        # Log event
        get_state_store().log_event(name, "policy_updated", policy_data)
        
        return {"status": "updated", "app": name, "policy": policy_data}
        
    except Exception as e:
        logger.error(f"Failed to update policy for app {name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/apps")
async def list_apps():
    """List all registered applications."""
    try:
        apps = get_state_store().list_apps()
        
        # Add runtime status
        for app in apps:
            status_result = get_app_manager().status(app["name"])
            app["status"] = status_result.get("status", "unknown")
            app["replicas"] = status_result.get("replicas", 0)
            app["ready_replicas"] = status_result.get("ready_replicas", 0)
        
        return {"apps": apps}
        
    except Exception as e:
        logger.error(f"Failed to list apps: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/apps/{name}/raw")
async def get_app_raw_spec(name: str):
    """Get the raw and parsed spec for an application."""
    try:
        # Get the parsed spec (normalized)
        parsed_spec = get_state_store().get_app(name)
        if not parsed_spec:
            raise HTTPException(status_code=404, detail=f"App {name} not found")
            
        # Get the raw spec (as submitted by user)
        raw_spec = get_state_store().get_raw_spec(name)
        
        return {
            "name": name,
            "raw": raw_spec,
            "parsed": parsed_spec
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get raw spec for app {name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/apps/{name}/logs")
async def get_app_logs(name: str, lines: int = 100):
    """Get logs for an application."""
    try:
        if name not in get_app_manager().instances:
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
        metrics_summary = get_auto_scaler().get_metrics_summary(name)
        scaling_history = get_state_store().get_scaling_history(name, limit=10)
        
        return {
            "app": name,
            "metrics": metrics_summary,
            "scaling_history": scaling_history
        }
        
    except Exception as e:
        logger.error(f"Failed to get metrics for app {name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/apps/{name}/simulateMetrics")
@leader_required
async def simulate_metrics(name: str, sim: SimulatedMetricsRequest):
    """Inject simulated metrics for an app and optionally trigger immediate autoscale evaluation.
    Helpful for verifying autoscaling without generating real load."""
    try:
        if name not in get_app_manager().instances:
            raise HTTPException(status_code=404, detail="App not running")

        instances = get_app_manager().instances[name]
        replica_count = len(instances)
        healthy = sum(1 for i in instances if i.state == 'ready')
        healthy_replicas = sim.healthyReplicas if sim.healthyReplicas is not None else healthy
        metrics = ScalingMetrics(
            rps=sim.rps,
            p95_latency_ms=sim.p95LatencyMs,
            active_connections=sim.activeConnections,
            cpu_percent=sim.cpuPercent,
            memory_percent=sim.memoryPercent,
            healthy_replicas=healthy_replicas,
            total_replicas=replica_count
        )
        get_auto_scaler().add_metrics(name, metrics)

        evaluation = None
        action = None
        if sim.evaluate:
            # Get app mode from database
            app_record = get_state_store().get_app(name)
            app_mode = app_record.mode if app_record else "auto"
            
            evaluation = get_auto_scaler().evaluate_scaling(name, replica_count, mode=app_mode)
            if evaluation.should_scale:
                result = get_app_manager().scale(name, evaluation.target_replicas)
                if result.get('status') == 'scaled':
                    get_auto_scaler().record_scaling_action(name, evaluation.target_replicas)
                    get_state_store().log_scaling_action(
                        name,
                        evaluation.current_replicas,
                        evaluation.target_replicas,
                        evaluation.reason,
                        evaluation.triggered_by,
                        evaluation.metrics.__dict__ if evaluation.metrics else None
                    )
                    action = {
                        "scaled": True,
                        "from": evaluation.current_replicas,
                        "to": evaluation.target_replicas,
                        "reason": evaluation.reason
                    }
                else:
                    action = {"scaled": False, "error": result}

        return {
            "app": name,
            "metrics_added": metrics.__dict__,
            "evaluation": {
                "should_scale": evaluation.should_scale if evaluation else None,
                "target_replicas": evaluation.target_replicas if evaluation else None,
                "reason": evaluation.reason if evaluation else None,
                "scale_factors": get_auto_scaler().last_scale_factors.get(name)
            } if evaluation else None,
            "action": action
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to simulate metrics for {name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/metrics")
async def get_system_metrics():
    """Get system-wide metrics for monitoring."""
    try:
        # Collect metrics from all components
        all_apps = get_state_store().list_apps()
        total_apps = len(all_apps)
        running_apps = 0
        total_instances = 0
        healthy_instances = 0
        
        for app in all_apps:
            app_name = app["name"]
            if app_name in get_app_manager().instances:
                instances = get_app_manager().instances[app_name]
                if instances:
                    running_apps += 1
                    total_instances += len(instances)
                    healthy_instances += sum(1 for inst in instances if inst.state == "ready")
        
        # Get nginx status
        nginx_status = get_nginx_manager().get_nginx_status()
        
        # Get health check summary
        health_summary = get_health_checker().get_health_summary()
        
        return {
            "timestamp": time.time(),
            "cluster": get_cluster_controller().get_cluster_status() if get_cluster_controller() else None,
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
        events = get_state_store().get_events(app, limit)
        return {"events": events}
        
    except Exception as e:
        logger.error(f"Failed to get events: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/cluster/status")
async def get_cluster_status():
    """Get detailed cluster status and membership."""
    if not get_cluster_controller():
        raise HTTPException(status_code=503, detail="Clustering not enabled")
        
    try:
        return get_cluster_controller().get_cluster_status()
    except Exception as e:
        logger.error(f"Failed to get cluster status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/cluster/leader")
async def get_cluster_leader():
    """Get current cluster leader information."""
    if not get_cluster_controller():
        raise HTTPException(status_code=503, detail="Clustering not enabled")
        
    try:
        leader_info = get_cluster_controller().get_leader_info()
        if leader_info:
            return leader_info
        else:
            raise HTTPException(status_code=503, detail="No leader elected")
    except Exception as e:
        logger.error(f"Failed to get cluster leader: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/cluster/health")
async def cluster_health_check():
    """Cluster-aware health check that includes leadership status."""
    if not get_cluster_controller():
        return {
            "status": "healthy",
            "clustering": "disabled",
            "timestamp": time.time(),
            "version": "1.0.0"
        }
        
    try:
        cluster_status = get_cluster_controller().get_cluster_status()
        is_ready = get_cluster_controller().is_cluster_ready()
        
        return {
            "status": "healthy" if is_ready else "degraded",
            "clustering": "enabled",
            "node_id": cluster_status["node_id"],
            "state": cluster_status["state"],
            "is_leader": cluster_status["is_leader"],
            "leader_id": cluster_status["leader_id"],
            "cluster_size": cluster_status["cluster_size"],
            "cluster_ready": is_ready,
            "timestamp": time.time(),
            "version": "1.0.0"
        }
    except Exception as e:
        logger.error(f"Failed cluster health check: {e}")
        return {
            "status": "unhealthy",
            "clustering": "error",
            "error": str(e),
            "timestamp": time.time(),
            "version": "1.0.0"
        }

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

