"""
Nginx management for Orchestry.
Manages Nginx configuration.
"""

import docker
import logging
import tempfile
import shutil
import os
from jinja2 import Template
from pathlib import Path
from typing import List, Dict
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

class DockerNginxManager:
    def __init__(self, nginx_container_name: str = None, conf_dir: str = None, template_path: str = "configs/nginx_template.conf"):
        self.docker_client = docker.from_env()

        self.nginx_container_name = nginx_container_name or os.getenv("ORCHESTRY_NGINX_CONTAINER")
        if not self.nginx_container_name:
            logger.error("ORCHESTRY_NGINX_CONTAINER environment variable is required. Please set it in .env file.")
            raise RuntimeError("Missing required environment variable: ORCHESTRY_NGINX_CONTAINER")
        conf_dir_name = os.getenv("ORCHESTRY_NGINX_CONF_DIR")
        if conf_dir_name:
            self.conf_dir = Path(conf_dir_name)
        else:
            logger.error("ORCHESTRY_NGINX_CONF_DIR environment variable is required. Please set it in .env file.")
            raise RuntimeError("Missing required environment variable: ORCHESTRY_NGINX_CONF_DIR")
        self.template_path = template_path or "configs/nginx_template.conf"
        self._load_template()

        # Ensure config directory exists
        self.conf_dir.mkdir(parents=True, exist_ok=True)

        # Ensure nginx container is running
        self._ensure_nginx_container()

    def _load_template(self):
        """Load the Nginx configuration template."""
        try:
            template_path = Path(self.template_path)
            if not template_path.exists():
                logger.error(f"Template file {self.template_path} not found")
                raise FileNotFoundError(f"Template file not found: {self.template_path}")

            template_content = template_path.read_text()
            self.template = Template(template_content)
            logger.info(f"Loaded template from {self.template_path}")

        except Exception as e:
            logger.error(f"Failed to load template: {e}")
            raise

    def _ensure_nginx_container(self):
        """Ensure the nginx container is running."""
        try:
            container = self.docker_client.containers.get(self.nginx_container_name)
            if container.status != "running":
                logger.info(f"Starting nginx container {self.nginx_container_name}")
                container.start()
                container.reload()
                if container.status == "running":
                    logger.info(f"Nginx container {self.nginx_container_name} started successfully")
            else:
                logger.info(f"Nginx container {self.nginx_container_name} is already running")
        except docker.errors.NotFound:
            logger.error(f"Nginx container {self.nginx_container_name} not found. Please start the Orchestry infrastructure.")
            raise Exception(f"Nginx container {self.nginx_container_name} not found")
        except Exception as e:
            logger.error(f"Failed to ensure nginx container: {e}")
            raise

    def _get_nginx_container(self):
        """Get the nginx container object."""
        try:
            return self.docker_client.containers.get(self.nginx_container_name)
        except docker.errors.NotFound:
            raise Exception(f"Nginx container {self.nginx_container_name} not found")

    def _validate_app_name(self, app_name: str) -> bool:
        """Validate the application name to prevent directory traversal."""
        if not app_name or not app_name.replace('_', '').replace('-', '').isalnum():
            logger.error(f"Invalid app name: {app_name}")
            return False
        return True

    def _validate_server(self, servers: List[Dict[str, str]]) -> bool:
        """Validate server configuration"""
        if not isinstance(servers, list):
            logger.error("Servers must be a list")
            return False
        for server in servers:
            if not isinstance(server, dict):
                logger.error(f"Invalid server config: {server}")
                return False
            if "ip" not in server or "port" not in server:
                logger.error(f"Server config missing required fields 'ip' or 'port': {server}")
                return False
            if not server["ip"] or not str(server["port"]).isdigit():
                logger.error(f"Server config has invalid ip or port: {server}")
                return False
        return True

    def update_upstreams(self, app_name: str, servers: List[Dict[str, str]]):
        """Update nginx upstream configuration for an app."""
        try:
            if not self._validate_app_name(app_name):
                return False

            if not servers:
                logger.warning(f"No servers provided for app {app_name}, removing config")
                self.remove_app_config(app_name)
                return False
            if not self._validate_server(servers):
                return False

            # Render the configuration
            config = self.template.render(app=app_name, servers=servers)
            conf_path = self.conf_dir / f"{app_name}.conf"
            backup_path = self.conf_dir / f"{app_name}.conf.backup"

            if conf_path.exists():
                shutil.copy2(conf_path, backup_path)

            # Write configuration to file
            with tempfile.NamedTemporaryFile(mode='w', delete=False, 
                                           dir=self.conf_dir, suffix='.tmp') as tmp_file:
                tmp_file.write(config)
                tmp_path = tmp_file.name
            shutil.move(tmp_path, conf_path)

            # Test nginx configuration
            nginx_container = self._get_nginx_container()
            test_result = nginx_container.exec_run(["nginx", "-t"])

            if test_result.exit_code != 0:
                logger.error(f"Nginx config test failed: {test_result.output}")
                if backup_path.exists():
                    shutil.move(backup_path, conf_path)
                    logger.info(f"Restored previous config for {app_name}")
                else:
                    conf_path.unlink()  # Remove invalid config
                return False

            # Reload nginx
            reload_result = nginx_container.exec_run(
                ["nginx", "-s", "reload"]
            )

            if reload_result.exit_code != 0:
                logger.error(f"Nginx reload failed: {reload_result.output}")
                if backup_path.exists():
                    shutil.move(backup_path, conf_path)
                    nginx_container.exec_run(["nginx", "-s", "reload"])
                    logger.info(f"Restored previous config for {app_name}")
                return False
            if backup_path.exists(): 
                backup_path.unlink()

            logger.info(f"Updated nginx config for {app_name} with {len(servers)} servers")
            return True

        except Exception as e:
            logger.error(f"Failed to update nginx config for {app_name}: {e}")
            return False

    def remove_app_config(self, app_name: str):
        """Remove nginx configuration for an app."""
        try:
            if not self._validate_app_name(app_name):
                return False

            conf_path = self.conf_dir / f"{app_name}.conf"
            if not conf_path.exists():
                logger.warning(f"Config for {app_name} does not exist")
                return True

            conf_path.unlink()

            nginx_container = self._get_nginx_container()
            test_result = nginx_container.exec_run(["nginx", "-t"])

            if test_result.exit_code != 0:
                logger.error(f"Nginx config test failed after removing {app_name}")
                return False

            reload_result = nginx_container.exec_run(["nginx", "-s", "reload"])
            if reload_result.exit_code != 0:
                logger.error(f"Nginx reload failed after removing {app_name}")
                return False

            logger.info(f"Removed nginx config for {app_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to remove nginx config for {app_name}: {e}")
            return False

    def get_nginx_status(self) -> Dict:
        """Get nginx status information."""
        try:
            nginx_container = self._get_nginx_container()

            # Get nginx status via container exec
            result = nginx_container.exec_run(
                ["curl", "-s", "http://localhost/nginx_status"]
            )

            if result.exit_code == 0:
                # Decode bytes to string if needed
                output = result.output
                if isinstance(output, bytes):
                    output = output.decode('utf-8')
                return self._parse_nginx_status(output)
            else:
                # Decode bytes to string if needed for error details
                error_details = result.output
                if isinstance(error_details, bytes):
                    error_details = error_details.decode('utf-8')
                return {"error": "Failed to get nginx status", "details": error_details}

        except Exception as e:
            logger.error(f"Failed to get nginx status: {e}")
            return {"error": str(e)}

    def _parse_nginx_status(self, status_text: str) -> Dict:
        """Parse nginx stub_status output."""
        try:
            lines = status_text.strip().split('\n')

            # Parse active connections
            active_line = lines[0]  # "Active connections: 1"
            active_connections = int(active_line.split(':')[1].strip())

            # Parse server stats
            stats_line = lines[2]  # "1 2 3"
            accepts, handled, requests = map(int, stats_line.split())

            # Parse reading/writing/waiting
            rw_line = lines[3]  # "Reading: 0 Writing: 1 Waiting: 0"
            rw_parts = rw_line.split()
            reading = int(rw_parts[1])
            writing = int(rw_parts[3])
            waiting = int(rw_parts[5])

            return {
                "active_connections": active_connections,
                "accepts": accepts,
                "handled": handled,
                "requests": requests,
                "reading": reading,
                "writing": writing,
                "waiting": waiting
            }

        except Exception as e:
            logger.error(f"Failed to parse nginx status: {e}")
            return {"error": "Failed to parse status"}

    def test_config(self) -> bool:
        """Test nginx configuration validity."""
        try:
            nginx_container = self._get_nginx_container()
            result = nginx_container.exec_run(
                ["nginx", "-t"]
            )
            return result.exit_code == 0
        except Exception:
            return False

    def list_app_configs(self) -> List[str]:
        """List all app configurations managed by this manager."""
        try:
            configs = []
            for conf_file in self.conf_dir.glob("*.conf"):
                if conf_file.suffix == '.conf' and not conf_file.stem.endswith('.backup'):
                    if conf_file.stem not in ["default", "nginx"]:  # Skip system configs
                        configs.append(conf_file.stem)
            return configs
        except Exception as e:
            logger.error(f"Failed to list app configs: {e}")
            return []

    def get_container_logs(self, lines: int = 100) -> str:
        """Get nginx container logs."""
        try:
            nginx_container = self._get_nginx_container()
            logs = nginx_container.logs(tail=lines, timestamps=True)
            return logs.decode('utf-8')
        except Exception as e:
            logger.error(f"Failed to get nginx logs: {e}")
            return f"Error getting logs: {e}"

    def restart_nginx(self) -> bool:
        """Restart the nginx container."""
        try:
            nginx_container = self._get_nginx_container()
            nginx_container.restart()
            logger.info(f"Restarted nginx container {self.nginx_container_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to restart nginx container: {e}")
            return False

NginxManager = DockerNginxManager

