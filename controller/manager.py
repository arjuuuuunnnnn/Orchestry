"""
Container lifecycle management using Docker API.
Handles container creation, scaling, health checks, and removal.
"""

import docker
import time
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass

from .state import StateStore
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
    def __init__(self, state_store: StateStore = None, nginx_manager: DockerNginxManager = None):
        self.docker_client = docker.from_env()
        self.state_store = state_store or StateStore()
        self.nginx_manager = nginx_manager or DockerNginxManager()
        self.health_checker = HealthChecker()
        self.instances: Dict[str, List[ContainerInstance]] = {}
        
        #create net if not exists
        self._ensure_network()
        
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
            app_spec = spec["spec"]
            
            #rn only for http servers
            if app_spec["type"] != "http":
                return {"error": "Only HTTP type is currently supported"}
                
            if "ports" not in app_spec or not app_spec["ports"]:
                return {"error": "HTTP apps must specify at least one port"}
                
            # Save to state store
            self.state_store.save_app(app_name, app_spec)
            
            # Initialize empty instance list
            self.instances[app_name] = []
            
            logger.info(f"Registered app {app_name}")
            return {"status": "registered", "app": app_name}
            
        except Exception as e:
            logger.error(f"Failed to register app: {e}")
            return {"error": str(e)}
    
    def start(self, app_name: str) -> dict:
        """Start the application containers."""
        try:
            logger.info(f"Starting app {app_name}")
            app_data = self.state_store.get_app(app_name)
            if not app_data:
                return {"error": f"App {app_name} not found"}
            
            logger.info(f"Got app data for {app_name}: {app_data}")
            
            # Extract app spec from the dictionary returned by state store
            app_spec = {
                "type": app_data["type"],
                "image": app_data["image"],
                "ports": app_data["ports"],
                "scaling": app_data["scaling"]
            }
            
            # Add resources if they exist
            if app_data.get("resources"):
                app_spec["resources"] = app_data["resources"]
            
            logger.info(f"Parsed app spec for {app_name}: {app_spec}")
            
            # Start with minimum replicas
            min_replicas = app_spec["scaling"].get("minReplicas", 1)
            logger.info(f"Starting {min_replicas} replicas for {app_name}")
            
            for i in range(min_replicas):
                logger.info(f"Starting container {i} for {app_name}")
                result = self._start_container(app_name, app_spec, i)
                logger.info(f"Container {i} start result: {result}")
            
            # Update nginx configuration
            self._update_nginx_config(app_name)
            
            logger.info(f"Started app {app_name} with {min_replicas} replicas")
            return {"status": "started", "app": app_name, "replicas": min_replicas}
            
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
            
            stopped_count = 0
            for instance in self.instances[app_name]:
                try:
                    container = self.docker_client.containers.get(instance.container_id)
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
            
            instances_info = []
            ready_count = 0
            
            for instance in self.instances[app_name]:
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
                
                if instance.state == "ready":
                    ready_count += 1
            
            return {
                "app": app_name,
                "status": "running" if ready_count > 0 else "degraded",
                "replicas": len(self.instances[app_name]),
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
                
            # app_data is a dictionary, not a tuple
            app_spec = {
                "type": app_data["type"],
                "image": app_data["image"],
                "ports": app_data["ports"],  # Already parsed as dict
                "scaling": app_data["scaling"],  # Already parsed as dict
                "resources": app_data["resources"]  # Already parsed as dict
            }
            
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
                logger.warning(f"Failed to update stats for container {instance.container_id}: {e}")
                instance.failures += 1
    
    def _update_nginx_config(self, app_name: str):
        """Update nginx configuration with current healthy instances."""
        if app_name not in self.instances:
            # No instances, remove config
            try:
                self.nginx_manager.remove_app_config(app_name)
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
                self.nginx_manager.update_upstreams(app_name, healthy_servers)
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
