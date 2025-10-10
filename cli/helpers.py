import os
import yaml
from platformdirs import user_config_dir
import typer
import requests

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
