"""
Container lifecycle management using Docker API.
Handles container creation, scaling, health checks, and removal.
"""

import docker
import time
import logging
import threading
from typing import Dict, List, Optional
from dataclasses import dataclass

from state.db import DatabaseManager, AppRecord
from .nginx import DockerNginxManager
from .health import HealthChecker

logger = logging.getLogger(__name__)

@dataclass
class ContainerInstance:
    container_id: str
    ip: str
    port: int
    state: str  # ready, draining, down
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    last_seen: float = 0.0
    failures: int = 0

class AppManager:
    def __init__(self, state_store: DatabaseManager = None, nginx_manager: DockerNginxManager = None):
        self.client = docker.from_env()
        self.state_store = state_store or DatabaseManager()
        self.nginx = nginx_manager or DockerNginxManager()
        self.health_checker = HealthChecker()
        self.instances = {}  # app_name -> list of ContainerInstance
        self._lock = threading.RLock()
        self._restart_lock = threading.RLock()
        self._shutdown = False
        self.monitoring_active = False
        self.monitoring_thread = None
        self._ensure_network()
        
    @property
    def docker_client(self):
        """Compatibility property for existing code."""
        return self.client

    # ------------------------- Reconciliation Logic -------------------------
    def reconcile_app(self, app_name: str) -> int:
        """Adopt existing Docker containers for a registered app.
        Returns number of adopted (ready) instances."""
        try:
            app_spec_record = self.state_store.get_app(app_name)
            if not app_spec_record:
                logger.warning(f"reconcile_app: app {app_name} not found in state store")
                return 0

            # Ensure list initialized
            if app_name not in self.instances:
                self.instances[app_name] = []

            # List containers with label
            containers = self.docker_client.containers.list(all=True, filters={"label": f"autoserve.app={app_name}"})
            adopted = 0
            for c in containers:
                try:
                    # Start if not running
                    if c.status != "running":
                        logger.info(f"Adopting container {c.name} (was {c.status}), starting...")
                        c.start()
                        c.reload()
                    # Extract replica index
                    replica_label = c.labels.get("autoserve.replica")
                    if replica_label is not None and replica_label.isdigit():
                        replica_index = int(replica_label)
                    else:
                        # Fallback: parse trailing dash number
                        parts = c.name.split('-')
                        replica_index = int(parts[-1]) if parts[-1].isdigit() else 0
                    network_settings = c.attrs.get("NetworkSettings", {})
                    ip = network_settings.get("Networks", {}).get("autoserve", {}).get("IPAddress", "")
                    port = app_spec_record.spec.get("ports", [{}])[0].get("containerPort", 0)
                    # Skip if already tracked
                    if any(inst.container_id == c.id for inst in self.instances[app_name]):
                        continue
                    instance = ContainerInstance(
                        container_id=c.id,
                        ip=ip,
                        port=port,
                        state="ready",
                        last_seen=time.time()
                    )
                    self.instances[app_name].append(instance)
                    adopted += 1
                except Exception as e:
                    logger.warning(f"Failed to adopt container {c.id} for {app_name}: {e}")
            if adopted:
                self._update_nginx_config(app_name)
            if adopted:
                logger.info(f"Reconciled {adopted} container(s) for {app_name}")
            return adopted
        except Exception as e:
            logger.error(f"reconcile_app failed for {app_name}: {e}")
            return 0

    def reconcile_all(self) -> Dict[str, int]:
        """Reconcile all registered apps. Returns mapping of app->adopted count."""
        results = {}
        try:
            apps = self.state_store.list_apps()
            for app in apps:
                adopted = self.reconcile_app(app["name"])
                results[app["name"]] = adopted
            return results
        except Exception as e:
            logger.error(f"reconcile_all failed: {e}")
            return results
        
    def _ensure_network(self):
        """Ensure AutoServe network exists for container communication."""
        try:
            self.docker_client.networks.get("autoserve")
        except docker.errors.NotFound:
            self.docker_client.networks.create(
                "autoserve", 
                driver="bridge",
                labels={"managed_by": "autoserve"}
            )
            
    def register(self, spec: dict) -> dict:
        """Register a new application with the given spec."""
        try:
            app_name = spec["metadata"]["name"]
            app_spec = spec["spec"].copy()  # Make a copy to avoid modifying original
            
            # Include scaling config from root level
            if "scaling" in spec:
                app_spec["scaling"] = spec["scaling"]
            
            #rn only for http servers
            if app_spec["type"] != "http":
                return {"error": "Only HTTP type is currently supported"}
                
            if "ports" not in app_spec or not app_spec["ports"]:
                return {"error": "HTTP apps must specify at least one port"}
            
            # Map healthCheck -> health for backward compatibility
            if "healthCheck" in app_spec:
                app_spec["health"] = app_spec.pop("healthCheck")
            
            # Merge metadata.labels into spec.labels
            if "labels" not in app_spec:
                app_spec["labels"] = {}
            if "labels" in spec.get("metadata", {}):
                app_spec["labels"].update(spec["metadata"]["labels"])
                
            # Create AppRecord with status='stopped' (no auto-start)
            now = time.time()
            app_record = AppRecord(
                name=app_name,
                spec=app_spec,
                status='stopped',  # Start as stopped, not running
                created_at=now,
                updated_at=now,
                replicas=0
            )
            self.state_store.save_app(app_record)
            
            # Initialize empty instance list
            self.instances[app_name] = []
            
            logger.info(f"Registered app {app_name} with status='stopped'")
            return {"status": "registered", "app": app_name}
            
        except Exception as e:
            logger.error(f"Failed to register app: {e}")
            return {"error": str(e)}
    
    def start(self, app_name: str) -> dict:
        """Start the application containers."""
        try:
            logger.info(f"Starting app {app_name}")
            app_record = self.state_store.get_app(app_name)
            if not app_record:
                return {"error": f"App {app_name} not found"}
            
            logger.info(f"Got app record for {app_name}: {app_record}")
            
            # Extract app spec from AppRecord
            app_spec = app_record.spec
            
            logger.info(f"Parsed app spec for {app_name}: {app_spec}")
            
            # Set status to running first
            app_record.status = 'running'
            app_record.updated_at = time.time()
            self.state_store.save_app(app_record)
            
            # Adopt existing containers first
            adopted = self.reconcile_app(app_name)

            # Determine existing replica indices
            existing_indices = set()
            for inst in self.instances.get(app_name, []):
                try:
                    c = self.docker_client.containers.get(inst.container_id)
                    idx_label = c.labels.get("autoserve.replica")
                    if idx_label and idx_label.isdigit():
                        existing_indices.add(int(idx_label))
                except Exception:
                    pass

            # Start additional replicas if below min
            scaling_config = app_spec.get("scaling", {})
            min_replicas = scaling_config.get("minReplicas", 1)
            logger.info(f"Ensuring minimum {min_replicas} replicas for {app_name} (adopted {adopted})")
            next_index = 0
            started = 0
            while len(self.instances.get(app_name, [])) < min_replicas:
                # Find next unused index
                while next_index in existing_indices:
                    next_index += 1
                logger.info(f"Creating new container replica index {next_index} for {app_name}")
                result = self._start_container(app_name, app_spec, next_index)
                if result:
                    existing_indices.add(next_index)
                    started += 1
                next_index += 1
            total = len(self.instances.get(app_name, []))
            
            # Update nginx configuration
            self._update_nginx_config(app_name)
            
            logger.info(f"App {app_name} now running with {total} replicas (adopted={adopted}, started={started})")
            return {"status": "started", "app": app_name, "replicas": total, "adopted": adopted, "started": started}
            
        except Exception as e:
            logger.error(f"Failed to start app {app_name}: {e}")
            return {"error": str(e)}
    
    def _start_container(self, app_name: str, app_spec: dict, replica_index: int) -> Optional[ContainerInstance]:
        """Start a single container instance."""
        try:
            container_port = app_spec["ports"][0]["containerPort"]
            
            # Container configuration
            container_config = {
                "image": app_spec["image"],
                "name": f"{app_name}-{replica_index}",
                "labels": {
                    "autoserve.app": app_name,
                    "autoserve.replica": str(replica_index),
                    "autoserve.type": app_spec["type"]
                },
                "network": "autoserve",
                "detach": True,
                "ports": {},
                "publish_all_ports": False,
            }
            
            #add resource limits if specified
            if "resources" in app_spec:
                resources = app_spec["resources"]
                if "cpu" in resources:
                    # Handle Kubernetes-style CPU specifications (e.g., "100m", "0.5", "1")
                    cpu_str = resources["cpu"]
                    if cpu_str.endswith("m"):
                        # Millicpus (e.g., "100m" = 0.1 CPU)
                        cpu_value = float(cpu_str[:-1]) / 1000
                    else:
                        # Regular CPU value (e.g., "0.5", "1")
                        cpu_value = float(cpu_str)
                    container_config["nano_cpus"] = int(cpu_value * 1_000_000_000)
                if "memory" in resources:
                    # Convert memory string to bytes
                    memory_str = resources["memory"]
                    if memory_str.endswith("Mi"):
                        memory_bytes = int(memory_str[:-2]) * 1024 * 1024
                        container_config["mem_limit"] = memory_bytes
            
            # Add environment variables if specified
            if "env" in app_spec:
                env_vars = {}
                for env in app_spec["env"]:
                    if env.get("valueFrom") == "sdk":
                        # Handle SDK-provided values
                        env_vars[env["name"]] = self._get_sdk_env_value(env["name"])
                    else:
                        env_vars[env["name"]] = env.get("value", "")
                container_config["environment"] = env_vars
            
            # Create container without port publishing
            container_config.pop("detach", None)  # Remove detach for create
            container = self.docker_client.containers.create(**container_config)
            container.start()
            
            # Wait for container to be running and get network info
            container.reload()
            if container.status != "running":
                raise Exception(f"Container failed to start: {container.status}")
            
            # Get container IP and port
            network_settings = container.attrs["NetworkSettings"]
            container_ip = network_settings["Networks"]["autoserve"]["IPAddress"]
            
            # Create instance record
            instance = ContainerInstance(
                container_id=container.id,
                ip=container_ip,
                port=container_port,
                state="ready",
                last_seen=time.time()
            )
            
            # Add to instances list
            if app_name not in self.instances:
                self.instances[app_name] = []
            self.instances[app_name].append(instance)
            
            logger.info(f"Started container {app_name}-{replica_index} at {container_ip}:{container_port}")
            return instance
            
        except Exception as e:
            logger.error(f"Failed to start container for {app_name}: {e}")
            logger.error(f"Container config was: {container_config}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return None
    
    def _get_sdk_env_value(self, env_name: str) -> str:
        """Get SDK-provided environment variable values."""
        # Get values from environment or use defaults for containerized services
        return ""
    
    def stop(self, app_name: str) -> dict:
        """Stop all containers for an application."""
        try:
            if app_name not in self.instances:
                return {"error": f"App {app_name} not found or not running"}
            
            # Set status to stopped first
            app_record = self.state_store.get_app(app_name)
            if app_record:
                app_record.status = 'stopped'
                app_record.updated_at = time.time()
                app_record.replicas = 0
                self.state_store.save_app(app_record)
            
            stopped_count = 0
            for instance in self.instances[app_name]:
                try:
                    container = self.client.containers.get(instance.container_id)
                    container.stop(timeout=30)
                    container.remove()
                    stopped_count += 1
                except Exception as e:
                    logger.warning(f"Failed to stop container {instance.container_id}: {e}")
            
            # Clear instances
            self.instances[app_name] = []
            
            # Remove nginx config
            self._update_nginx_config(app_name)
            
            logger.info(f"Stopped {stopped_count} containers for app {app_name}")
            return {"status": "stopped", "app": app_name, "containers_stopped": stopped_count}
            
        except Exception as e:
            logger.error(f"Failed to stop app {app_name}: {e}")
            return {"error": str(e)}
    
    def status(self, app_name: str) -> dict:
        """Get the status of an application."""
        try:
            app_data = self.state_store.get_app(app_name)
            if not app_data:
                return {"error": f"App {app_name} not found"}
            
            if app_name not in self.instances:
                return {
                    "app": app_name,
                    "status": "stopped",
                    "replicas": 0,
                    "instances": []
                }
            
            # Update container stats
            self._update_container_stats(app_name)
            
            # Clean up down containers
            self._cleanup_down_containers(app_name)
            
            instances_info = []
            ready_count = 0
            running_count = 0
            
            for instance in self.instances[app_name]:
                # Skip down containers in the instances list
                if instance.state == "down":
                    continue
                    
                instance_info = {
                    "container_id": instance.container_id[:12],  # Short ID
                    "ip": instance.ip,
                    "port": instance.port,
                    "state": instance.state,
                    "cpu_percent": instance.cpu_percent,
                    "memory_percent": instance.memory_percent,
                    "failures": instance.failures
                }
                instances_info.append(instance_info)
                running_count += 1
                
                if instance.state == "ready":
                    ready_count += 1
            
            return {
                "app": app_name,
                "status": "running" if ready_count > 0 else ("degraded" if running_count > 0 else "stopped"),
                "replicas": running_count,  # Only count non-down containers
                "ready_replicas": ready_count,
                "instances": instances_info
            }
            
        except Exception as e:
            logger.error(f"Failed to get status for app {app_name}: {e}")
            return {"error": str(e)}
    
    def scale(self, app_name: str, replicas: int) -> dict:
        """Manually scale an application to the specified number of replicas."""
        try:
            if app_name not in self.instances:
                return {"error": f"App {app_name} not found or not running"}
            
            current_replicas = len(self.instances[app_name])
            
            if replicas == current_replicas:
                return {"status": "no_change", "app": app_name, "replicas": replicas}
            
            app_data = self.state_store.get_app(app_name)
            if not app_data:
                return {"error": f"App {app_name} specification not found"}
                
            # app_data is an AppRecord object
            app_spec = app_data.spec.copy()
            
            if replicas > current_replicas:
                # Scale up
                for i in range(current_replicas, replicas):
                    self._start_container(app_name, app_spec, i)
            else:
                # Scale down
                containers_to_remove = self.instances[app_name][replicas:]
                for instance in containers_to_remove:
                    self._stop_container(instance)
                self.instances[app_name] = self.instances[app_name][:replicas]
            
            # Update nginx configuration
            self._update_nginx_config(app_name)
            
            logger.info(f"Scaled app {app_name} from {current_replicas} to {replicas} replicas")
            return {"status": "scaled", "app": app_name, "replicas": replicas}
            
        except Exception as e:
            logger.error(f"Failed to scale app {app_name}: {e}")
            return {"error": str(e)}
    
    def _stop_container(self, instance: ContainerInstance):
        """Stop and remove a single container."""
        try:
            container = self.docker_client.containers.get(instance.container_id)
            container.stop(timeout=30)
            container.remove()
        except Exception as e:
            logger.warning(f"Failed to stop container {instance.container_id}: {e}")
    
    def _update_container_stats(self, app_name: str):
        """Update CPU and memory statistics for all containers of an app."""
        if app_name not in self.instances:
            return
        
        for instance in self.instances[app_name]:
            try:
                container = self.docker_client.containers.get(instance.container_id)
                
                # Check if container is still running
                container.reload()  # Refresh container state
                if container.status != "running":
                    logger.info(f"Container {instance.container_id[:12]} is {container.status}, marking as down")
                    instance.state = "down"
                    instance.cpu_percent = 0.0
                    instance.memory_percent = 0.0
                    continue
                
                stats = container.stats(stream=False)
                
                # Calculate CPU percentage
                cpu_stats = stats.get("cpu_stats", {})
                precpu_stats = stats.get("precpu_stats", {})
                
                cpu_usage = cpu_stats.get("cpu_usage", {})
                precpu_usage = precpu_stats.get("cpu_usage", {})
                
                total_usage = cpu_usage.get("total_usage", 0)
                prev_total_usage = precpu_usage.get("total_usage", 0)
                
                system_cpu_usage = cpu_stats.get("system_cpu_usage", 0)
                prev_system_cpu_usage = precpu_stats.get("system_cpu_usage", 0)
                
                # Get number of CPUs with fallback methods
                num_cpus = 1  # Default fallback
                if "percpu_usage" in cpu_usage:
                    num_cpus = len(cpu_usage["percpu_usage"])
                elif "online_cpus" in cpu_stats:
                    num_cpus = cpu_stats["online_cpus"]
                else:
                    # Try to get from /proc/cpuinfo or use default
                    try:
                        import os
                        num_cpus = os.cpu_count() or 1
                    except:
                        num_cpus = 1
                
                cpu_delta = total_usage - prev_total_usage
                system_delta = system_cpu_usage - prev_system_cpu_usage
                
                if system_delta > 0 and cpu_delta >= 0:
                    instance.cpu_percent = (cpu_delta / system_delta) * num_cpus * 100.0
                else:
                    instance.cpu_percent = 0.0
                
                # Calculate memory percentage with error handling
                memory_stats = stats.get("memory_stats", {})
                memory_usage = memory_stats.get("usage", 0)
                memory_limit = memory_stats.get("limit", 1)  # Avoid division by zero
                
                if memory_limit > 0:
                    instance.memory_percent = (memory_usage / memory_limit) * 100.0
                else:
                    instance.memory_percent = 0.0
                
                instance.last_seen = time.time()
                
            except Exception as e:
                # Container is likely stopped or removed
                logger.info(f"Container {instance.container_id[:12]} is no longer accessible: {e}")
                instance.state = "down"
                instance.cpu_percent = 0.0
                instance.memory_percent = 0.0
                instance.failures += 1

    def _cleanup_down_containers(self, app_name: str):
        """Remove down containers from tracking after a grace period."""
        if app_name not in self.instances:
            return
            
        # Remove containers that have been down for more than 30 seconds
        current_time = time.time()
        containers_to_remove = []
        
        for i, instance in enumerate(self.instances[app_name]):
            if instance.state == "down":
                # If it's been down for more than 30 seconds, remove it from tracking
                if hasattr(instance, 'last_seen') and (current_time - instance.last_seen) > 30:
                    containers_to_remove.append(i)
                elif not hasattr(instance, 'last_seen'):
                    # If no last_seen timestamp, remove immediately
                    containers_to_remove.append(i)
        
        # Remove from list in reverse order to maintain indices
        for i in reversed(containers_to_remove):
            removed_instance = self.instances[app_name].pop(i)
            logger.info(f"Removed down container {removed_instance.container_id[:12]} from tracking for {app_name}")
            
        # If no instances left, remove the app key
        if not self.instances[app_name]:
            del self.instances[app_name]
            logger.info(f"No running instances left for {app_name}")
    
    def _update_nginx_config(self, app_name: str):
        """Update nginx configuration with current healthy instances."""
        if app_name not in self.instances:
            # No instances, remove config
            try:
                self.nginx.remove_app_config(app_name)
            except:
                pass
            return
        
        # Filter for healthy instances
        healthy_servers = []
        for instance in self.instances[app_name]:
            if instance.state == "ready":
                healthy_servers.append({
                    "ip": instance.ip,
                    "port": instance.port
                })
        
        if healthy_servers:
            try:
                self.nginx.update_upstreams(app_name, healthy_servers)
            except Exception as e:
                logger.error(f"Failed to update nginx config for {app_name}: {e}")
    
    def cleanup_orphaned_containers(self):
        """Clean up containers that are not tracked in our state."""
        try:
            # Get all autoserve containers
            containers = self.docker_client.containers.list(
                filters={"label": "autoserve.app"}
            )
            
            for container in containers:
                app_name = container.labels.get("autoserve.app")
                container_id = container.id
                # Skip cleanup if app exists in state store (will be or was reconciled)
                if self.state_store.get_app(app_name):
                    continue
                
                # Check if this container is tracked
                is_tracked = False
                if app_name in self.instances:
                    for instance in self.instances[app_name]:
                        if instance.container_id == container_id:
                            is_tracked = True
                            break
                
                if not is_tracked:
                    logger.info(f"Cleaning up orphaned container {container_id}")
                    container.stop(timeout=10)
                    container.remove()
                    
        except Exception as e:
            logger.error(f"Failed to cleanup orphaned containers: {e}")

    def start_container_monitoring(self):
        """Start the container monitoring thread."""
        if self.monitoring_active:
            logger.warning("Container monitoring is already active")
            return
        
        self.monitoring_active = True
        self.monitoring_thread = threading.Thread(target=self._container_monitoring_loop, daemon=True)
        self.monitoring_thread.start()
        logger.info("Started container monitoring thread")

    def stop_container_monitoring(self):
        """Stop the container monitoring thread."""
        self.monitoring_active = False
        if self.monitoring_thread and self.monitoring_thread.is_alive():
            self.monitoring_thread.join(timeout=5)
        logger.info("Stopped container monitoring thread")

    def _container_monitoring_loop(self):
        """Main loop for monitoring container health and ensuring minReplicas."""
        logger.info("Container monitoring loop started")
        
        while self.monitoring_active:
            try:
                self._check_and_restart_containers()
                self._ensure_min_replicas()
                time.sleep(10)  # Check every 10 seconds
            except Exception as e:
                logger.error(f"Error in container monitoring loop: {e}")
                time.sleep(5)  # Wait a bit before retrying

    def _check_and_restart_containers(self):
        """Check all tracked containers and restart any that are stopped."""
        with self._restart_lock:
            for app_name in list(self.instances.keys()):
                app_spec_record = self.state_store.get_app(app_name)
                if not app_spec_record:
                    continue
                    
                instances_to_remove = []
                instances_to_restart = []
                
                for i, instance in enumerate(self.instances[app_name]):
                    try:
                        # Get container object
                        container = self.docker_client.containers.get(instance.container_id)
                        container.reload()
                        
                        # Check if container is not running
                        if container.status != "running":
                            logger.warning(f"Container {container.name} ({container.id[:12]}) for app {app_name} is {container.status}")
                            
                            # Try to restart the existing container first
                            if container.status in ["stopped", "exited"]:
                                try:
                                    logger.info(f"Attempting to restart existing container {container.name}")
                                    container.start()
                                    container.reload()
                                    
                                    if container.status == "running":
                                        logger.info(f"Successfully restarted container {container.name}")
                                        instance.state = "ready"
                                        instance.last_seen = time.time()
                                        continue
                                except Exception as restart_e:
                                    logger.warning(f"Failed to restart existing container {container.name}: {restart_e}")
                            
                            # If restart failed or container is in bad state, mark for recreation
                            instances_to_remove.append(i)
                            instances_to_restart.append(instance)
                            
                    except docker.errors.NotFound:
                        # Container no longer exists, mark for recreation
                        logger.warning(f"Container {instance.container_id[:12]} for app {app_name} no longer exists")
                        instances_to_remove.append(i)
                        instances_to_restart.append(instance)
                    except Exception as e:
                        logger.error(f"Error checking container {instance.container_id[:12]} for app {app_name}: {e}")
                
                # Remove failed instances and recreate them
                for idx in reversed(instances_to_remove):
                    self.instances[app_name].pop(idx)
                
                # Recreate containers for failed instances
                for failed_instance in instances_to_restart:
                    self._recreate_container(app_name, failed_instance)

    def _recreate_container(self, app_name: str, failed_instance: ContainerInstance):
        """Recreate a failed container."""
        try:
            logger.info(f"Recreating container for app {app_name}")
            
            app_spec_record = self.state_store.get_app(app_name)
            if not app_spec_record:
                logger.error(f"App spec not found for {app_name}")
                return
            
            # Extract container port from app spec
            container_port = app_spec_record.get("ports", [{}])[0].get("containerPort", 8080)
            
            # Find next available replica index
            existing_indices = set()
            for inst in self.instances.get(app_name, []):
                try:
                    container = self.docker_client.containers.get(inst.container_id)
                    idx_label = container.labels.get("autoserve.replica")
                    if idx_label and idx_label.isdigit():
                        existing_indices.add(int(idx_label))
                except:
                    pass
            
            next_index = 0
            while next_index in existing_indices:
                next_index += 1
            
            # Create new container with same configuration as before
            container_name = f"{app_name}-{next_index}"
            
            # Check if a container with this name already exists
            try:
                existing_container = self.docker_client.containers.get(container_name)
                if existing_container.status == "running":
                    logger.info(f"Container {container_name} already running, adopting it")
                    # Adopt the existing running container
                    network_settings = existing_container.attrs.get("NetworkSettings", {})
                    container_ip = network_settings.get("Networks", {}).get("autoserve", {}).get("IPAddress", "")
                    
                    instance = ContainerInstance(
                        container_id=existing_container.id,
                        ip=container_ip,
                        port=container_port,
                        state="ready",
                        last_seen=time.time()
                    )
                    self.instances[app_name].append(instance)
                    self._update_nginx_config(app_name)
                    return
                else:
                    # Start the existing stopped container
                    logger.info(f"Starting existing stopped container {container_name}")
                    existing_container.start()
                    existing_container.reload()
                    
                    if existing_container.status == "running":
                        network_settings = existing_container.attrs.get("NetworkSettings", {})
                        container_ip = network_settings.get("Networks", {}).get("autoserve", {}).get("IPAddress", "")
                        
                        instance = ContainerInstance(
                            container_id=existing_container.id,
                            ip=container_ip,
                            port=container_port,
                            state="ready",
                            last_seen=time.time()
                        )
                        self.instances[app_name].append(instance)
                        self._update_nginx_config(app_name)
                        return
                    
            except docker.errors.NotFound:
                pass  # Container doesn't exist, we'll create it
            except Exception as e:
                logger.warning(f"Error checking existing container {container_name}: {e}")
            
            # Create completely new container
            container_config = {
                "image": app_spec_record["image"],
                "name": container_name,
                "network": "autoserve",
                "detach": True,
                "labels": {
                    "autoserve.app": app_name,
                    "autoserve.replica": str(next_index),
                    "managed_by": "autoserve"
                },
                "restart_policy": {"Name": "unless-stopped"}
            }
            
            # Add resource limits if specified
            if "resources" in app_spec_record:
                resources = app_spec_record["resources"]
                if "cpu" in resources:
                    cpu_str = resources["cpu"]
                    if cpu_str.endswith("m"):
                        cpu_value = float(cpu_str[:-1]) / 1000
                    else:
                        cpu_value = float(cpu_str)
                    container_config["nano_cpus"] = int(cpu_value * 1_000_000_000)
                if "memory" in resources:
                    memory_str = resources["memory"]
                    if memory_str.endswith("Mi"):
                        memory_bytes = int(memory_str[:-2]) * 1024 * 1024
                        container_config["mem_limit"] = memory_bytes
            
            # Add environment variables if specified
            if "env" in app_spec_record:
                env_vars = {}
                for env in app_spec_record["env"]:
                    if env.get("valueFrom") == "sdk":
                        env_vars[env["name"]] = self._get_sdk_env_value(env["name"])
                    else:
                        env_vars[env["name"]] = env.get("value", "")
                container_config["environment"] = env_vars
            
            # Create and start container
            container_config.pop("detach", None)
            container = self.docker_client.containers.create(**container_config)
            container.start()
            container.reload()
            
            if container.status != "running":
                raise Exception(f"Container failed to start: {container.status}")
            
            # Get container IP
            network_settings = container.attrs["NetworkSettings"]
            container_ip = network_settings["Networks"]["autoserve"]["IPAddress"]
            
            # Create new instance record
            instance = ContainerInstance(
                container_id=container.id,
                ip=container_ip,
                port=container_port,
                state="ready",
                last_seen=time.time()
            )
            
            self.instances[app_name].append(instance)
            self._update_nginx_config(app_name)
            
            logger.info(f"Successfully recreated container {container_name} for app {app_name}")
            
        except Exception as e:
            logger.error(f"Failed to recreate container for app {app_name}: {e}")

    def _ensure_min_replicas(self):
        """Ensure all RUNNING apps maintain their minimum replica count."""
        with self._restart_lock:
            for app_name in list(self.instances.keys()):
                try:
                    app_spec_record = self.state_store.get_app(app_name)
                    if not app_spec_record:
                        continue
                    
                    # Only maintain replicas for running apps
                    if app_spec_record.status != 'running':
                        logger.debug(f"Skipping app {app_name} with status '{app_spec_record.status}'")
                        continue
                    
                    # Get minReplicas from scaling policy
                    scaling_policy = app_spec_record.spec.get("scaling", {})
                    min_replicas = scaling_policy.get("minReplicas", 1)
                    
                    # Count healthy running instances
                    healthy_instances = []
                    for instance in self.instances.get(app_name, []):
                        try:
                            container = self.client.containers.get(instance.container_id)
                            container.reload()
                            if container.status == "running" and instance.state == "ready":
                                healthy_instances.append(instance)
                        except docker.errors.NotFound:
                            continue  # Container will be handled by _check_and_restart_containers
                        except Exception:
                            continue
                    
                    current_healthy = len(healthy_instances)
                    
                    if current_healthy < min_replicas:
                        needed = min_replicas - current_healthy
                        logger.info(f"App {app_name} has {current_healthy}/{min_replicas} minimum replicas, creating {needed} more")
                        
                        for _ in range(needed):
                            self._create_additional_replica(app_name)
                            
                except Exception as e:
                    logger.error(f"Error ensuring min replicas for app {app_name}: {e}")

    def _create_additional_replica(self, app_name: str):
        """Create an additional replica for an app."""
        try:
            app_spec_record = self.state_store.get_app(app_name)
            if not app_spec_record:
                return
            
            # Find next available replica index
            existing_indices = set()
            containers = self.client.containers.list(all=True, filters={"label": f"autoserve.app={app_name}"})
            
            for container in containers:
                idx_label = container.labels.get("autoserve.replica")
                if idx_label and idx_label.isdigit():
                    existing_indices.add(int(idx_label))
            
            next_index = 0
            while next_index in existing_indices:
                next_index += 1
            
            # Create new replica
            self._create_container_replica(app_name, app_spec_record.spec, next_index)
            logger.info(f"Created additional replica {next_index} for app {app_name}")
            
        except Exception as e:
            logger.error(f"Failed to create additional replica for app {app_name}: {e}")

    def _create_container_replica(self, app_name: str, app_spec: dict, replica_index: int):
        """Create a single container replica."""
        container_port = app_spec.get("ports", [{}])[0].get("containerPort", 8080)
        container_name = f"{app_name}-{replica_index}"
        
        # Check if container already exists and handle appropriately
        try:
            existing_container = self.docker_client.containers.get(container_name)
            if existing_container.status == "running":
                logger.info(f"Container {container_name} already running")
                return  # Already handled
            else:
                existing_container.start()
                existing_container.reload()
                if existing_container.status == "running":
                    logger.info(f"Restarted existing container {container_name}")
                    return
        except docker.errors.NotFound:
            pass  # Container doesn't exist, create it
        
        container_config = {
            "image": app_spec["image"],
            "name": container_name,
            "network": "autoserve",
            "detach": True,
            "labels": {
                "autoserve.app": app_name,
                "autoserve.replica": str(replica_index),
                "managed_by": "autoserve"
            },
            "restart_policy": {"Name": "unless-stopped"}
        }
        
        # Add resource limits if specified
        if "resources" in app_spec:
            resources = app_spec["resources"]
            if "cpu" in resources:
                cpu_str = resources["cpu"]
                if cpu_str.endswith("m"):
                    cpu_value = float(cpu_str[:-1]) / 1000
                else:
                    cpu_value = float(cpu_str)
                container_config["nano_cpus"] = int(cpu_value * 1_000_000_000)
            if "memory" in resources:
                memory_str = resources["memory"]
                if memory_str.endswith("Mi"):
                    memory_bytes = int(memory_str[:-2]) * 1024 * 1024
                    container_config["mem_limit"] = memory_bytes
        
        # Add environment variables if specified
        if "env" in app_spec:
            env_vars = {}
            for env in app_spec["env"]:
                if env.get("valueFrom") == "sdk":
                    env_vars[env["name"]] = self._get_sdk_env_value(env["name"])
                else:
                    env_vars[env["name"]] = env.get("value", "")
            container_config["environment"] = env_vars
        
        # Create and start container
        container = self.docker_client.containers.create(**container_config)
        container.start()
        container.reload()
        
        if container.status != "running":
            raise Exception(f"Container failed to start: {container.status}")
        
        # Get container IP
        network_settings = container.attrs["NetworkSettings"]
        container_ip = network_settings["Networks"]["autoserve"]["IPAddress"]
        
        # Create instance record
        instance = ContainerInstance(
            container_id=container.id,
            ip=container_ip,
            port=container_port,
            state="ready",
            last_seen=time.time()
        )
        
        if app_name not in self.instances:
            self.instances[app_name] = []
        self.instances[app_name].append(instance)
        
        self._update_nginx_config(app_name)
