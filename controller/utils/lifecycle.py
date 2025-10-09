"""
Lifecycle management for the Orchestry Controller.
Handles startup and shutdown events for all components.
"""
import logging
import threading
import time
import os
from typing import Optional, Any

from controller.manager import AppManager
from state.db import get_database_manager
from controller.nginx import DockerNginxManager
from controller.scaler import AutoScaler, ScalingPolicy
from controller.health import HealthChecker
from controller.cluster import DistributedController

logger = logging.getLogger(__name__)

# Global components - initialized when starting the API
app_manager: Optional[AppManager] = None
state_store: Optional[Any] = None
nginx_manager: Optional[DockerNginxManager] = None
auto_scaler: Optional[AutoScaler] = None
health_checker: Optional[HealthChecker] = None
cluster_controller: Optional[DistributedController] = None

# Background monitoring task
monitoring_task: Optional[threading.Thread] = None
monitoring_active = False

# Nginx request tracking to compute RPS
_prev_nginx_requests: Optional[int] = None
_prev_nginx_time: Optional[float] = None


def get_app_manager() -> Optional[AppManager]:
    """Get the global app manager instance."""
    return app_manager


def get_state_store() -> Optional[Any]:
    """Get the global state store instance."""
    return state_store


def get_nginx_manager() -> Optional[DockerNginxManager]:
    """Get the global nginx manager instance."""
    return nginx_manager


def get_auto_scaler() -> Optional[AutoScaler]:
    """Get the global auto scaler instance."""
    return auto_scaler


def get_health_checker() -> Optional[HealthChecker]:
    """Get the global health checker instance."""
    return health_checker


def get_cluster_controller() -> Optional[DistributedController]:
    """Get the global cluster controller instance."""
    return cluster_controller


def get_nginx_tracking():
    """Get nginx request tracking state."""
    global _prev_nginx_requests, _prev_nginx_time
    return _prev_nginx_requests, _prev_nginx_time


def set_nginx_tracking(requests: Optional[int], timestamp: Optional[float]):
    """Set nginx request tracking state."""
    global _prev_nginx_requests, _prev_nginx_time
    _prev_nginx_requests = requests
    _prev_nginx_time = timestamp


def on_become_leader():
    """Called when this node becomes the cluster leader"""
    logger.info("👑 This node has become the cluster leader - taking control of operations")

    if app_manager and auto_scaler:
        try:
            adopted_summary = app_manager.reconcile_all()
            logger.info(f"✅ Leader reconciled existing containers: {adopted_summary}")
        except Exception as e:
            logger.error(f"❌ Leader failed to reconcile existing containers: {e}")
        
        try:
            apps = state_store.list_apps()
            logger.info(f"🔄 Restoring scaling policies for {len(apps)} apps from database")
            
            for app in apps:
                app_name = app["name"]
                try:
                    # Get full app record to access the spec with scaling config
                    app_record = state_store.get_app(app_name)
                    if app_record and app_record.spec:
                        scaling_config = app_record.spec.get("scaling", {})
                        
                        if scaling_config:  # Only restore if scaling config exists
                            policy = ScalingPolicy(
                                min_replicas=scaling_config["minReplicas"],
                                max_replicas=scaling_config["maxReplicas"],
                                target_rps_per_replica=scaling_config["targetRPSPerReplica"],
                                max_p95_latency_ms=scaling_config["maxP95LatencyMs"],
                                scale_out_threshold_pct=scaling_config["scaleOutThresholdPct"],
                                scale_in_threshold_pct=scaling_config["scaleInThresholdPct"],
                                window_seconds=scaling_config.get("windowSeconds", 60),  # Optional field
                                cooldown_seconds=scaling_config.get("cooldownSeconds", 300)  # Optional field
                            )
                            
                            auto_scaler.set_policy(app_name, policy)
                            logger.info(f"✅ Restored scaling policy for {app_name}: targetRPS={scaling_config['targetRPSPerReplica']}, thresholds={scaling_config['scaleOutThresholdPct']}%/{scaling_config['scaleInThresholdPct']}%")
                        else:
                            logger.debug(f"No scaling config found in spec for {app_name}")
                    else:
                        logger.warning(f"Could not get app record for {app_name}")
                        
                except Exception as e:
                    logger.error(f"❌ Failed to restore scaling policy for {app_name}: {e}")
                    
            logger.info("✅ Leader completed scaling policy restoration from database")
        except Exception as e:
            logger.error(f"❌ Leader failed to restore scaling policies: {e}")
        
        # Start container monitoring for automatic restarts and minReplicas enforcement
        app_manager.start_container_monitoring()
        
        # Clean only containers whose app spec no longer exists
        try:
            app_manager.cleanup_orphaned_containers()
            logger.info("✅ Leader completed orphaned container cleanup")
        except Exception as e:
            logger.error(f"❌ Leader failed orphaned container cleanup: {e}")


def on_lose_leadership():
    """Called when this node loses leadership"""
    logger.warning("💔 This node has lost cluster leadership - stepping down from operations")
    # Follower nodes should stop active operations and just serve read requests
    if app_manager:
        app_manager.stop_container_monitoring()


def on_cluster_change(nodes):
    """Called when cluster membership changes"""
    node_count = len(nodes)
    node_ids = [node.node_id for node in nodes.values()]
    logger.info(f"🔄 Cluster membership changed: {node_count} nodes - {node_ids}")


def background_monitoring():
    """Background thread for monitoring and autoscaling."""
    logger.info("Started background monitoring thread")
    
    while monitoring_active:
        try:
            if not app_manager or not auto_scaler:
                time.sleep(5)
                continue
                
            # Only run monitoring on the leader node
            if cluster_controller and not cluster_controller.is_leader:
                time.sleep(5)
                continue
            
            # Get list of running apps only - don't scale stopped apps
            all_apps = state_store.list_apps()
            apps = [app for app in all_apps if app.get("status") == "running"]

            # Fetch nginx status once per loop for reuse
            nginx_status = nginx_manager.get_nginx_status() if nginx_manager else None
            
            for app_info in apps:
                app_name = app_info["name"]
                
                try:
                    # Use the scaler to observe metrics and make scaling decisions
                    auto_scaler.observe(app_name, nginx_status)
                    
                    decision = auto_scaler.decide(app_name)
                    
                    if decision and decision.action != "none":
                        logger.info(f"Scaling decision for {app_name}: {decision.action} to {decision.target_replicas} replicas. Reason: {decision.reason}")
                        
                        try:
                            if decision.action == "scale_out":
                                app_manager.scale_app(app_name, decision.target_replicas)
                            elif decision.action == "scale_in":
                                app_manager.scale_app(app_name, decision.target_replicas)
                        except Exception as e:
                            logger.error(f"Failed to execute scaling action for {app_name}: {e}")
                
                except Exception as e:
                    logger.error(f"Error during monitoring loop for {app_name}: {e}")
            
            # Sleep between monitoring cycles
            time.sleep(5)
            
        except Exception as e:
            logger.error(f"Error in background monitoring thread: {e}")
            time.sleep(5)
    
    logger.info("Background monitoring thread stopped")


async def startup_event():
    """Initialize all components when the API starts."""
    global app_manager, state_store, nginx_manager, auto_scaler, health_checker, cluster_controller
    global monitoring_task, monitoring_active
    
    try:
        # Initialize PostgreSQL High Availability database cluster
        logger.info("🚀 Initializing PostgreSQL HA database cluster...")
        state_store = get_database_manager()
        
        # Initialize distributed controller cluster with leader election
        logger.info("🏗️  Initializing distributed controller cluster...")
        cluster_controller = DistributedController(
            node_id=os.getenv("CLUSTER_NODE_ID"),
            hostname=os.getenv("CLUSTER_HOSTNAME", "localhost"),
            port=int(os.getenv("ORCHESTRY_PORT", "8000")),
            db_manager=state_store
        )
        
        # Set up cluster event handlers
        cluster_controller.on_become_leader = on_become_leader
        cluster_controller.on_lose_leadership = on_lose_leadership
        cluster_controller.on_cluster_change = on_cluster_change
        
        # Start the cluster
        cluster_controller.start()
        
        # Initialize other components
        nginx_manager = DockerNginxManager()
        auto_scaler = AutoScaler()
        health_checker = HealthChecker()
        app_manager = AppManager(state_store, nginx_manager)
        
        # Start health checker
        await health_checker.start()
        
        # Reconcile existing containers BEFORE cleanup
        try:
            adopted_summary = app_manager.reconcile_all()
            logger.info(f"Reconciliation summary on startup: {adopted_summary}")
            
            # Re-register scaling policies for all existing apps from database
            logger.info("Restoring scaling policies from database on startup")
            apps = state_store.list_apps()
            logger.info(f"Found {len(apps)} apps to restore scaling policies for")
            
            for app in apps:
                app_name = app["name"]
                logger.info(f"Attempting to restore scaling policy for {app_name}")
                try:
                    # Get full app record to access the spec with scaling config
                    app_record = state_store.get_app(app_name)
                    if app_record and app_record.spec:
                        scaling_config = app_record.spec.get("scaling", {})
                        
                        if scaling_config:  # Only restore if scaling config exists
                            logger.info(f"Scaling config for {app_name}: {scaling_config}")
                            
                            policy = ScalingPolicy(
                                min_replicas=scaling_config["minReplicas"],
                                max_replicas=scaling_config["maxReplicas"],
                                target_rps_per_replica=scaling_config["targetRPSPerReplica"],
                                max_p95_latency_ms=scaling_config["maxP95LatencyMs"],
                                scale_out_threshold_pct=scaling_config["scaleOutThresholdPct"],
                                scale_in_threshold_pct=scaling_config["scaleInThresholdPct"],
                                window_seconds=scaling_config.get("windowSeconds", 60),  # Optional field
                                cooldown_seconds=scaling_config.get("cooldownSeconds", 300)  # Optional field
                            )
                            
                            auto_scaler.set_policy(app_name, policy)
                            logger.info(f"Successfully restored scaling policy for {app_name}: targetRPS={scaling_config['targetRPSPerReplica']}, thresholds={scaling_config['scaleOutThresholdPct']}%/{scaling_config['scaleInThresholdPct']}%")
                        else:
                            logger.debug(f"No scaling config found in spec for {app_name}")
                    else:
                        logger.warning(f"Could not get app record for {app_name}")
                        
                except Exception as e:
                    logger.error(f"Failed to restore scaling policy for {app_name}: {e}")
                    import traceback
                    logger.error(f"Full traceback: {traceback.format_exc()}")
                    
        except Exception as e:
            logger.error(f"Failed initial reconciliation: {e}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")

        # Start background monitoring (runs on all nodes but only leader does work)
        monitoring_active = True
        monitoring_task = threading.Thread(target=background_monitoring, daemon=True)
        monitoring_task.start()
        
        # Wait a bit for cluster to elect leader, then do cleanup
        # Container monitoring and cleanup will be started by the leader
        logger.info("Waiting for leader election before starting container operations...")
        
        logger.info("Orchestry Controller API started successfully")
        
    except Exception as e:
        logger.error(f"Failed to start controller: {e}")
        raise


async def shutdown_event():
    """Clean up resources when shutting down."""
    global monitoring_active, health_checker, app_manager, cluster_controller
    
    monitoring_active = False
    
    if cluster_controller:
        cluster_controller.stop()
    
    if app_manager:
        app_manager.stop_container_monitoring()
    
    if health_checker:
        await health_checker.stop()
    
    if state_store:
        state_store.close()
    
    logger.info("Orchestry Controller API shut down")
