import typer
import requests
from dotenv import load_dotenv
import os
import json
import yaml
from typing import Optional

load_dotenv()

app = typer.Typer(name="autoserve", help="AutoServe SDK CLI")

# Default values for local development
AUTOSERVE_HOST = os.getenv("AUTOSERVE_HOST", "localhost")
AUTOSERVE_PORT = os.getenv("AUTOSERVE_PORT", "8000")

API_URL = f"http://{AUTOSERVE_HOST}:{AUTOSERVE_PORT}"

def check_service_running():
    """Check if AutoServe controller is running and provide helpful error messages."""
    try:
        response = requests.get(f"{API_URL}/health", timeout=5)
        if response.status_code == 200:
            return True
    except requests.exceptions.ConnectionError:
        typer.echo("❌ AutoServe controller is not running.", err=True)
        typer.echo("", err=True)
        typer.echo("💡 To start AutoServe:", err=True)
        typer.echo("   docker-compose up -d", err=True)
        typer.echo("", err=True)
        typer.echo("   Or use the quick start script:", err=True)
        typer.echo("   ./start.sh", err=True)
        typer.echo("", err=True)
        raise typer.Exit(1)
    except requests.exceptions.Timeout:
        typer.echo("  AutoServe controller is not responding (timeout).", err=True)
        typer.echo("   Check if the service is healthy: docker-compose ps", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"❌ Error connecting to AutoServe: {e}", err=True)
        raise typer.Exit(1)
    
    return False

@app.command()
def register(config: str):
    """Register an app from YAML/JSON spec."""
    check_service_running()
    
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
            f"{API_URL}/apps/register", 
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
    check_service_running()
    response = requests.post(f"{API_URL}/apps/{name}/up")
    typer.echo(response.json())

@app.command()  
def down(name: str):
    """Stop the app."""
    check_service_running()
    response = requests.post(f"{API_URL}/apps/{name}/down")
    typer.echo(response.json())

@app.command()
def status(name: str):
    """Check app status."""
    check_service_running()
    response = requests.get(f"{API_URL}/apps/{name}/status")
    typer.echo(response.json())

@app.command()
def scale(name: str, replicas: int):
    """Scale app to specific replica count."""
    check_service_running()
    # First, get app info to check scaling mode
    try:
        info_response = requests.get(f"{API_URL}/apps/{name}/status")
        if info_response.status_code == 404:
            typer.echo(f" App '{name}' not found", err=True)
            raise typer.Exit(1)
        elif info_response.status_code != 200:
            typer.echo(f" Error: {info_response.json()}", err=True)
            raise typer.Exit(1)
        
        app_info = info_response.json()
        app_mode = app_info.get('mode', 'auto')
        
        # Inform user about the scaling mode
        if app_mode == 'manual':
            typer.echo(f"  Scaling '{name}' to {replicas} replicas (manual mode)")
        else:
            typer.echo(f"  Scaling '{name}' to {replicas} replicas (auto mode - may be overridden by autoscaler)")
        
        # Perform the scaling
        response = requests.post(
            f"{API_URL}/apps/{name}/scale",
            json={"replicas": replicas}
        )
        
        if response.status_code == 200:
            result = response.json()
            typer.echo(" " + str(result))
            
            # Additional guidance for auto mode
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
    check_service_running()
    response = requests.get(f"{API_URL}/apps")
    typer.echo(response.json())

@app.command()
def metrics(name: Optional[str] = None):
    """Get system or app metrics."""
    check_service_running()
    if name:
        response = requests.get(f"{API_URL}/apps/{name}/metrics")
    else:
        response = requests.get(f"{API_URL}/metrics")
        
    typer.echo(response.json())

@app.command()
def info():
    """Show AutoServe system information and status."""
    try:
        response = requests.get(f"{API_URL}/health", timeout=5)
        if response.status_code == 200:
            typer.echo(" AutoServe Controller: Running")
            typer.echo(f"   API: {API_URL}")
            
            # Get apps count
            apps_response = requests.get(f"{API_URL}/apps")
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
            typer.echo(" AutoServe Controller: Not healthy")
    except requests.exceptions.ConnectionError:
        typer.echo(" AutoServe Controller: Not running")
        typer.echo("")
        typer.echo(" To start: docker-compose up -d")
    except Exception as e:
        typer.echo(f" Error checking status: {e}")

@app.command()
def spec(name: str, raw: bool = False):
    """Get app specification. Use --raw to see the original submitted spec."""
    check_service_running()
    try:
        response = requests.get(f"{API_URL}/apps/{name}/raw")
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
                typer.echo("No raw spec available (app may have been registered before persistence was implemented)")
        else:
            # Show the parsed/normalized spec
            parsed = data.get("parsed", {})
            # Remove internal fields
            for field in ["created_at", "updated_at"]:
                parsed.pop(field, None)
            typer.echo(yaml.dump(parsed, default_flow_style=False))
            
    except Exception as e:
        typer.echo(f" Error: {e}", err=True)
        raise typer.Exit(1)

if __name__ == "__main__":
    app()

