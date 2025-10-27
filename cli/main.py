import typer
import requests
from dotenv import load_dotenv
import os
import json
import yaml
from typing import Optional

import cli.helpers as helpers

load_dotenv()

app = typer.Typer(name="orchestry", help="Orchestry SDK CLI")

ORCHESTRY_URL = helpers.load_config()

@app.command()
def config():
    """Configure orchestry by adding ORCHESTRY_HOST and orchestry_PORT"""
    typer.echo("To configure orchestry, please enter the following details:")
    ORCHESTRY_HOST = typer.prompt("Host (e.g., localhost or an IP address)")
    ORCHESTRY_PORT = typer.prompt("Port (e.g., 8000)")

    typer.echo(f"Connecting to orchestry at http://{ORCHESTRY_HOST}:{ORCHESTRY_PORT}...")
    if helpers.check_service_running(f"http://{ORCHESTRY_HOST}:{ORCHESTRY_PORT}") == True:
        helpers.save_config(ORCHESTRY_HOST, ORCHESTRY_PORT)
        typer.echo(f"Configuration saved to {helpers.CONFIG_FILE}")
    else:
        typer.echo("Failed to connect to the specified host and port. Please ensure the orchestry controller is running.", err=True)
        raise typer.Exit(1)

@app.command()
def register(config: str):
    """Register an app from YAML/JSON spec."""
    if helpers.check_service_running(ORCHESTRY_URL) == False:
        typer.echo(" orchestry controller is not running, run 'orchestry config' to configure", err=True)
        raise typer.Exit(1)
    if not os.path.exists(config):
        typer.echo(f" Config file '{config}' not found", err=True)
        raise typer.Exit(1)

    try:
        with open(config) as f:
            if config.endswith(('.yml', '.yaml')):
                spec = yaml.safe_load(f)
            else:
                spec = json.load(f)

        response = requests.post(
            f"{ORCHESTRY_URL}/apps/register",
            json=spec,
            headers={"Content-Type": "application/json"}
        )

        if response.status_code == 200:
            result = response.json()
            typer.echo(" App registered successfully!")
            typer.echo(json.dumps(result, indent=2))
        else:
            typer.echo(f" Registration failed: {response.json()}")
            raise typer.Exit(1)

    except Exception as e:
        typer.echo(f" Error: {e}", err=True)
        raise typer.Exit(1)

@app.command()
def up(name: str):
    """Start the app."""
    if helpers.check_service_running(ORCHESTRY_URL) == False:
        typer.echo(" orchestry controller is not running, run 'orchestry config' to configure", err=True)
        raise typer.Exit(1)

    response = requests.post(f"{ORCHESTRY_URL}/apps/{name}/up")
    res = response.json()
    typer.echo(json.dumps(res, indent=2))

@app.command()
def down(name: str):
    """Stop the app."""
    if helpers.check_service_running(ORCHESTRY_URL) == False:
        typer.echo(" orchestry controller is not running, run 'orchestry config' to configure", err=True)
        raise typer.Exit(1)
    response = requests.post(f"{ORCHESTRY_URL}/apps/{name}/down")
    res = response.json()
    typer.echo(json.dumps(res, indent=2))

@app.command()
def status(name: str):
    """Check app status."""
    if helpers.check_service_running(ORCHESTRY_URL) == False:
        typer.echo(" orchestry controller is not running, run 'orchestry config' to configure", err=True)
        raise typer.Exit(1)

    response = requests.get(f"{ORCHESTRY_URL}/apps/{name}/status")
    res = response.json()
    typer.echo(json.dumps(res, indent=2))

@app.command()
def scale(name: str, replicas: int):
    """Scale app to specific replica count."""
    if helpers.check_service_running(ORCHESTRY_URL) == False:
        typer.echo(" orchestry controller is not running, run 'orchestry config' to configure", err=True)
        raise typer.Exit(1)

    try:
        info_response = requests.get(f"{ORCHESTRY_URL}/apps/{name}/status")
        if info_response.status_code == 404:
            typer.echo(f" App '{name}' not found", err=True)
            raise typer.Exit(1)
        elif info_response.status_code != 200:
            typer.echo(f" Error: {info_response.json()}", err=True)
            raise typer.Exit(1)

        app_info = info_response.json()
        app_mode = app_info.get('mode', 'auto')

        if app_mode == 'manual':
            typer.echo(f"  Scaling '{name}' to {replicas} replicas (manual mode)")
        else:
            typer.echo(f"  Scaling '{name}' to {replicas} replicas (auto mode - may be overridden by autoscaler)")

        response = requests.post(
            f"{ORCHESTRY_URL}/apps/{name}/scale",
            json={"replicas": replicas}
        )

        if response.status_code == 200:
            result = response.json()
            typer.echo(" " + str(json.dumps(result, indent=2)))

            if app_mode == 'auto':
                typer.echo("\n Tip: This app uses automatic scaling. To use manual scaling, set 'mode: manual' in the scaling section of your YAML spec.")
        else:
            typer.echo(f" Error: {response.json()}", err=True)
            raise typer.Exit(1)

    except requests.exceptions.RequestException as e:
        typer.echo(f" Error: Unable to connect to API - {e}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f" Error: {e}", err=True)
        raise typer.Exit(1)

@app.command()
def list():
    """List all applications.""" 
    if helpers.check_service_running(ORCHESTRY_URL) == False:
        typer.echo(" orchestry controller is not running, run 'orchestry config' to configure", err=True)
        raise typer.Exit(1)

    response = requests.get(f"{ORCHESTRY_URL}/apps")
    res = response.json()
    typer.echo(json.dumps(res, indent=2))

@app.command()
def metrics(name: Optional[str] = None):
    """Get system or app metrics."""
    if helpers.check_service_running(ORCHESTRY_URL) == False:
        typer.echo(" orchestry controller is not running, run 'orchestry config' to configure", err=True)
        raise typer.Exit(1)

    if name:
        response = requests.get(f"{ORCHESTRY_URL}/apps/{name}/metrics")
    else:
        response = requests.get(f"{ORCHESTRY_URL}/metrics")

    res = response.json()
    typer.echo(json.dumps(res, indent=2))

@app.command()
def info():
    """Show orchestry system information and status."""
    try:
        response = requests.get(f"{ORCHESTRY_URL}/health", timeout=5)
        if response.status_code == 200:
            typer.echo(" orchestry Controller: Running")
            typer.echo(f"   API: {ORCHESTRY_URL}")

            apps_response = requests.get(f"{ORCHESTRY_URL}/apps")
            if apps_response.status_code == 200:
                apps = apps_response.json()
                typer.echo(f"   Apps: {len(apps)} registered")
            typer.echo("")
            typer.echo(" Docker Services:")
            import subprocess
            result = subprocess.run(
                ["docker-compose", "ps", "--format", "table"], 
                capture_output=True, text=True, cwd="."
            )
            if result.returncode == 0:
                typer.echo(result.stdout)
            else:
                typer.echo("   Unable to check Docker services")

        else:
            typer.echo(" orchestry Controller: Not healthy")
    except requests.exceptions.ConnectionError:
        typer.echo(" orchestry Controller: Not running")
        typer.echo("")
        typer.echo(" To start: docker-compose up -d")
    except Exception as e:
        typer.echo(f" Error checking status: {e}")

@app.command()
def spec(name: str, raw: bool = False):
    """Get app specification. Use --raw to see the original submitted spec."""
    if helpers.check_service_running(ORCHESTRY_URL) == False:
        typer.echo(" orchestry controller is not running, run 'orchestry config' to configure", err=True)
        raise typer.Exit(1)

    try:
        response = requests.get(f"{ORCHESTRY_URL}/apps/{name}/raw")
        if response.status_code == 404:
            typer.echo(f" App '{name}' not found", err=True)
            raise typer.Exit(1)
        elif response.status_code != 200:
            typer.echo(f" Error: {response.json()}", err=True)
            raise typer.Exit(1)

        data = response.json()

        if raw:
            if data.get("raw"):
                typer.echo(yaml.dump(data["raw"], default_flow_style=False))
            else:
                typer.echo("No raw spec available")
        else:
            parsed = data.get("parsed", {})
            for field in ["created_at", "updated_at"]:
                parsed.pop(field, None)
            typer.echo(yaml.dump(parsed, default_flow_style=False))

    except Exception as e:
        typer.echo(f" Error: {e}", err=True)
        raise typer.Exit(1)

@app.command()
def logs(
    name: str,
    lines: int = typer.Option(100, "--lines", "-n", help="Number of log lines to retrieve"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output (not yet implemented)")
):
    """Get logs for an application."""
    if helpers.check_service_running(ORCHESTRY_URL) == False:
        typer.echo(" orchestry controller is not running, run 'orchestry config' to configure", err=True)
        raise typer.Exit(1)

    try:
        response = requests.get(f"{ORCHESTRY_URL}/apps/{name}/logs", params={"lines": lines})

        if response.status_code == 404:
            typer.echo(f" App '{name}' not found or not running", err=True)
            raise typer.Exit(1)
        elif response.status_code != 200:
            typer.echo(f" Error: {response.json()}", err=True)
            raise typer.Exit(1)

        data = response.json()
        logs_list = data.get("logs", [])
        total_containers = data.get("total_containers", 0)

        if not logs_list:
            typer.echo(f" No logs available for app '{name}'")
            return

        typer.echo(f" Logs for '{name}' ({total_containers} container(s)):")
        typer.echo("")

        # Display logs sorted by timestamp
        for log_entry in logs_list:
            timestamp = log_entry.get("timestamp", 0)
            container_id = log_entry.get("container", "unknown")
            message = log_entry.get("message", "")

            # Format timestamp
            from datetime import datetime
            dt = datetime.fromtimestamp(timestamp)
            time_str = dt.strftime("%Y-%m-%d %H:%M:%S")

            # Color-code by container (simple approach using container ID)
            typer.echo(f"{time_str} [{container_id}] {message}")

        if follow:
            typer.echo("\n Note: Log following (--follow/-f) is not yet implemented")

    except requests.exceptions.RequestException as e:
        typer.echo(f" Error: Unable to connect to API - {e}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f" Error: {e}", err=True)
        raise typer.Exit(1)

@app.command()
def cluster(opts: str):
    """Get cluster information(status, leader, health)"""
    if helpers.check_service_running(ORCHESTRY_URL) == False:
        typer.echo(" orchestry controller is not running, run 'orchestry config' to configure", err=True)
        raise typer.Exit(1)

    try:
        response = requests.get(f"{ORCHESTRY_URL}/cluster/{opts}")
        if response.status_code == 404:
            typer.echo(f"Cluster '{opts}' not found", err=True)
            raise typer.Exit(1)
        elif response.status_code != 200:
            typer.echo(f"Error: {response.json()}", err=True)
            raise typer.Exit(1)
        res = response.json()
        typer.echo(json.dumps(res, indent=2))
    except requests.exceptions.RequestException as e:
        typer.echo(f" Error: Unable to connect to API - {e}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f" Error: {e}", err=True)
        raise typer.Exit(1)

@app.command()
def events():
    """Get recent events"""
    if helpers.check_service_running(ORCHESTRY_URL) == False:
        typer.echo(" orchestry controller is not running, run 'orchestry config' to configure", err=True)
        raise typer.Exit(1)

    try:
        response = requests.get(f"{ORCHESTRY_URL}/events")
        if response.status_code != 200:
            typer.echo(f" Error: {response.json()}", err=True)
            raise typer.Exit(1)
        res = response.json()
        typer.echo(json.dumps(res, indent=2))
    except requests.exceptions.RequestException as e:
        typer.echo(f" Error: Unable to connect to API - {e}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f" Error: {e}", err=True)
        raise typer.Exit(1)


if __name__ == "__main__":
    if not ORCHESTRY_URL:
        typer.echo("orchestry is not configured. Please run 'orchestry config' to set it up.", err=True)
        raise typer.Exit(1)
    app()

