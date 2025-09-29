import typer
import requests
from dotenv import load_dotenv
import os
import json
import yaml
from typing import Optional
from platformdirs import user_config_dir

load_dotenv()

app = typer.Typer(name="orchestry", help="Orchestry SDK CLI")

CONFIG_DIR = user_config_dir("orchestry", "orchestry")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.yaml")

def save_config(host, port):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    data = {"host": host, "port": port}
    with open(CONFIG_FILE, "w") as f:
        yaml.dump(data, f)

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            data = yaml.safe_load(f)
            if data and "host" in data and "port" in data:
                return f"http://{data['host']}:{data['port']}"
    return None

ORCHESTRY_URL = load_config()

def check_service_running(API_URL):
    """Check if orchestry controller is running and provide helpful error messages."""
    try:
        if API_URL is None:
            typer.echo(" orchestry is not configured.", err=True)
            typer.echo(" Please run 'orchestry config' to set it up.", err=True)
            raise typer.Exit(1)
        response = requests.get(f"{API_URL}/health", timeout=5)
        if response.status_code == 200:
            return True
    except requests.exceptions.ConnectionError:
        typer.echo(" orchestry controller is not running.", err=True)
        typer.echo("", err=True)
        typer.echo(" Please ensure you are running orchestry", err=True)
        typer.echo(" To start orchestry:", err=True)
        typer.echo(" docker-compose up -d", err=True)
        typer.echo("", err=True)
        typer.echo(" Or use the quick start script:", err=True)
        typer.echo(" ./start.sh", err=True)
        typer.echo("", err=True)
        raise typer.Exit(1)
    except requests.exceptions.Timeout:
        typer.echo(" orchestry controller is not responding (timeout).", err=True)
        typer.echo(" Check if the service is healthy: docker-compose ps", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f" Error connecting to orchestry: {e}", err=True)
        raise typer.Exit(1)
    return False


@app.command()
def config():
    """Configure orchestry by adding ORCHESTRY_HOST and orchestry_PORT"""
    typer.echo("To configure orchestry, please enter the following details:")
    ORCHESTRY_HOST = typer.prompt("Host (e.g., localhost or an IP address)")
    ORCHESTRY_PORT = typer.prompt("Port (e.g., 8000)")

    typer.echo(f"Connecting to orchestry at http://{ORCHESTRY_HOST}:{ORCHESTRY_PORT}...")
    if check_service_running(f"http://{ORCHESTRY_HOST}:{ORCHESTRY_PORT}") == True:
        save_config(ORCHESTRY_HOST, ORCHESTRY_PORT)
        typer.echo(f"Configuration saved to {CONFIG_FILE}")
    else:
        typer.echo("Failed to connect to the specified host and port. Please ensure the orchestry controller is running.", err=True)
        raise typer.Exit(1)

@app.command()
def register(config: str):
    """Register an app from YAML/JSON spec."""
    if check_service_running(ORCHESTRY_URL) == False:
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
    if check_service_running(ORCHESTRY_URL) == False:
        typer.echo(" orchestry controller is not running, run 'orchestry config' to configure", err=True)
        raise typer.Exit(1)

    response = requests.post(f"{ORCHESTRY_URL}/apps/{name}/up")
    typer.echo(response.json())

@app.command()
def down(name: str):
    """Stop the app."""
    if check_service_running(ORCHESTRY_URL) == False:
        typer.echo(" orchestry controller is not running, run 'orchestry config' to configure", err=True)
        raise typer.Exit(1)
    response = requests.post(f"{ORCHESTRY_URL}/apps/{name}/down")
    typer.echo(response.json())

@app.command()
def status(name: str):
    """Check app status."""
    if check_service_running(ORCHESTRY_URL) == False:
        typer.echo(" orchestry controller is not running, run 'orchestry config' to configure", err=True)
        raise typer.Exit(1)

    response = requests.get(f"{ORCHESTRY_URL}/apps/{name}/status")
    typer.echo(response.json())

@app.command()
def scale(name: str, replicas: int):
    """Scale app to specific replica count."""
    if check_service_running(ORCHESTRY_URL) == False:
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
            typer.echo(" " + str(result))

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
    if check_service_running(ORCHESTRY_URL) == False:
        typer.echo(" orchestry controller is not running, run 'orchestry config' to configure", err=True)
        raise typer.Exit(1)

    response = requests.get(f"{ORCHESTRY_URL}/apps")
    typer.echo(response.json())

@app.command()
def metrics(name: Optional[str] = None):
    """Get system or app metrics."""
    if check_service_running(ORCHESTRY_URL) == False:
        typer.echo(" orchestry controller is not running, run 'orchestry config' to configure", err=True)
        raise typer.Exit(1)

    if name:
        response = requests.get(f"{ORCHESTRY_URL}/apps/{name}/metrics")
    else:
        response = requests.get(f"{ORCHESTRY_URL}/metrics")

    typer.echo(response.json())

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
    if check_service_running(ORCHESTRY_URL) == False:
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

if __name__ == "__main__":
    if not ORCHESTRY_URL:
        typer.echo("orchestry is not configured. Please run 'orchestry config' to set it up.", err=True)
        raise typer.Exit(1)
    app()

