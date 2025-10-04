"""
Health checking functionality for HTTP applications.
Performs HTTP health checks and manages container health state.
"""

import aiohttp
import asyncio
import time
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class HealthCheckConfig:
    path: str = "/healthz"
    interval_seconds: int = 5
    timeout_seconds: int = 2
    failure_threshold: int = 3
    success_threshold: int = 1

@dataclass
class HealthStatus:
    is_healthy: bool
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    last_check: float = 0.0
    last_success: float = 0.0
    response_time_ms: float = 0.0

class HealthChecker:
    def __init__(self):
        self.health_configs: Dict[str, HealthCheckConfig] = {}
        self.health_status: Dict[str, HealthStatus] = {}
        self.container_info: Dict[str, Dict] = {}  # Store container IP and port info
        self.session: Optional[aiohttp.ClientSession] = None
        self._running = False
        self._health_change_callback = None  # Callback for when health status changes

    def set_health_change_callback(self, callback):
        """Set callback function to be called when container health status changes."""
        self._health_change_callback = callback

    async def start(self):
        """Start the health checker background task."""
        if not self._running:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            )
            self._running = True
            asyncio.create_task(self._health_check_loop())
            logger.info("Health checker started")

    async def stop(self):
        """Stop the health checker and clean up resources."""
        self._running = False
        if self.session:
            await self.session.close()
            self.session = None
        logger.info("Health checker stopped")

    def add_target(self, container_id: str, ip: str, port: int, config: HealthCheckConfig):
        """Add a container to health monitoring."""
        target_key = f"{ip}:{port}"
        self.health_configs[container_id] = config or HealthCheckConfig()
        self.health_status[container_id] = HealthStatus(is_healthy=False)
        self.container_info[container_id] = {"ip": ip, "port": port}
        logger.info(f"Added health check target: {target_key} for container {container_id}")

    def remove_target(self, container_id: str):
        """Remove a container from health monitoring."""
        self.health_configs.pop(container_id, None)
        self.health_status.pop(container_id, None)
        self.container_info.pop(container_id, None)
        logger.info(f"Removed health check target: {container_id}")

    def get_health_status(self, container_id: str) -> Optional[HealthStatus]:
        """Get the current health status of a container."""
        return self.health_status.get(container_id)

    def is_healthy(self, container_id: str) -> bool:
        """Check if a container is currently healthy."""
        status = self.health_status.get(container_id)
        return status.is_healthy if status else False

    async def _health_check_loop(self):
        """Main health checking loop."""
        while self._running:
            try:
                # Create tasks for all health checks
                tasks = []
                for container_id in list(self.health_configs.keys()):
                    task = asyncio.create_task(self._check_container_health(container_id))
                    tasks.append(task)

                # Wait for all health checks to complete
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

                # Wait before next round of checks
                await asyncio.sleep(1)  # Check every second, but respect individual intervals

            except Exception as e:
                logger.error(f"Error in health check loop: {e}")
                await asyncio.sleep(5)  # Back off on errors

    async def _check_container_health(self, container_id: str):
        """Perform health check for a single container."""
        config = self.health_configs.get(container_id)
        status = self.health_status.get(container_id)

        if not config or not status:
            return

        # Check if it's time for a health check
        now = time.time()
        if now - status.last_check < config.interval_seconds:
            return

        # Get container info (this would be passed from the manager)
        # For now, we'll need to reconstruct this from the container_id
        # In a real implementation, we'd store this mapping
        try:
            # This is a placeholder - in reality we'd get this info from the manager
            container_info = self._get_container_info(container_id)
            if not container_info:
                return

            ip, port = container_info["ip"], container_info["port"]

            # Perform the health check
            start_time = time.time()
            is_healthy = await self._perform_http_check(ip, port, config)
            response_time = (time.time() - start_time) * 1000  # Convert to ms

            # Update status
            status.last_check = now
            status.response_time_ms = response_time

            if is_healthy:
                status.consecutive_successes += 1
                status.consecutive_failures = 0
                status.last_success = now

                # Mark as healthy if we've had enough consecutive successes
                if status.consecutive_successes >= config.success_threshold:
                    was_unhealthy = not status.is_healthy
                    status.is_healthy = True
                    if was_unhealthy:
                        logger.info(f"Container {container_id} is now healthy")
                        # Notify callback of health status change
                        if self._health_change_callback:
                            self._health_change_callback(container_id, True)
            else:
                status.consecutive_failures += 1
                status.consecutive_successes = 0

                # Mark as unhealthy if we've had too many consecutive failures
                if status.consecutive_failures >= config.failure_threshold:
                    was_healthy = status.is_healthy
                    status.is_healthy = False
                    if was_healthy:
                        logger.warning(f"Container {container_id} is now unhealthy")
                        # Notify callback of health status change
                        if self._health_change_callback:
                            self._health_change_callback(container_id, False)

        except Exception as e:
            logger.error(f"Health check failed for container {container_id}: {e}")
            status.consecutive_failures += 1
            status.consecutive_successes = 0
            if status.consecutive_failures >= config.failure_threshold:
                was_healthy = status.is_healthy
                status.is_healthy = False
                if was_healthy:
                    logger.warning(f"Container {container_id} marked unhealthy due to health check failure")
                    # Notify callback of health status change
                    if self._health_change_callback:
                        self._health_change_callback(container_id, False)

    def _get_container_info(self, container_id: str) -> Optional[Dict]:
        """Get container IP and port info."""
        return self.container_info.get(container_id)

    @staticmethod
    def create_config_from_spec(health_spec: Dict) -> HealthCheckConfig:
        """Create HealthCheckConfig from YAML health specification."""
        return HealthCheckConfig(
            path=health_spec.get("path", "/healthz"),
            interval_seconds=health_spec.get("periodSeconds", 5),
            timeout_seconds=health_spec.get("timeoutSeconds", 2),
            failure_threshold=health_spec.get("failureThreshold", 3),
            success_threshold=health_spec.get("successThreshold", 1)
        )

    async def _perform_http_check(self, ip: str, port: int, config: HealthCheckConfig) -> bool:
        """Perform an HTTP health check against a container."""
        if not self.session:
            return False

        try:
            url = f"http://{ip}:{port}{config.path}"

            async with self.session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=config.timeout_seconds)
            ) as response:
                # Consider 2xx and 3xx responses as healthy
                return 200 <= response.status < 400

        except asyncio.TimeoutError:
            logger.debug(f"Health check timeout for {ip}:{port}")
            return False
        except aiohttp.ClientError as e:
            logger.debug(f"Health check connection error for {ip}:{port}: {e}")
            return False
        except Exception as e:
            logger.warning(f"Unexpected error during health check for {ip}:{port}: {e}")
            return False

    def get_all_healthy_containers(self) -> List[str]:
        """Get list of all healthy container IDs."""
        healthy = []
        for container_id, status in self.health_status.items():
            if status.is_healthy:
                healthy.append(container_id)
        return healthy

    def get_health_summary(self) -> Dict:
        """Get a summary of all health checks."""
        summary = {
            "total_targets": len(self.health_status),
            "healthy_targets": 0,
            "unhealthy_targets": 0,
            "targets": {}
        }

        for container_id, status in self.health_status.items():
            if status.is_healthy:
                summary["healthy_targets"] += 1
            else:
                summary["unhealthy_targets"] += 1

            summary["targets"][container_id] = {
                "healthy": status.is_healthy,
                "consecutive_failures": status.consecutive_failures,
                "consecutive_successes": status.consecutive_successes,
                "last_success": status.last_success,
                "response_time_ms": status.response_time_ms
            }

        return summary
