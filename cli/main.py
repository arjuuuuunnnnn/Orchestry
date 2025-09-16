import typer
import requests
from dotenv import load_dotenv
import os
import json
import yaml
from typing import Optional

load_dotenv()

app = typer.Typer(name="autoserve", help="AutoServe SDK CLI")

API_URL = os.getenv("API_URL", "http://localhost:8000")

@app.command()
def register(config: str):
    """Register an app from YAML/JSON spec."""
    if not os.path.exists(config):
        typer.echo(f"Error: Config file '{config}' not found")
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
        
        typer.echo(response.json())
        
    except Exception as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(1)

@app.command()
def up(name: str):
    """Start the app."""
    response = requests.post(f"{API_URL}/apps/{name}/up")
    typer.echo(response.json())

@app.command()  
def down(name: str):
    """Stop the app."""
    response = requests.post(f"{API_URL}/apps/{name}/down")
    typer.echo(response.json())

@app.command()
def status(name: str):
    """Check app status."""
    response = requests.get(f"{API_URL}/apps/{name}/status")
    typer.echo(response.json())

@app.command()
def scale(name: str, replicas: int):
    """Scale app to specific replica count."""
    response = requests.post(
        f"{API_URL}/apps/{name}/scale",
        json={"replicas": replicas}
    )
    typer.echo(response.json())

@app.command()
def list():
    """List all applications.""" 
    response = requests.get(f"{API_URL}/apps")
    typer.echo(response.json())

@app.command()
def metrics(name: Optional[str] = None):
    """Get system or app metrics."""
    if name:
        response = requests.get(f"{API_URL}/apps/{name}/metrics")
    else:
        response = requests.get(f"{API_URL}/metrics")
        
    typer.echo(response.json())

@app.command()
def spec(name: str, raw: bool = False):
    """Get app specification. Use --raw to see the original submitted spec."""
    try:
        response = requests.get(f"{API_URL}/apps/{name}/raw")
        if response.status_code == 404:
            typer.echo(f"Error: App '{name}' not found")
            raise typer.Exit(1)
        elif response.status_code != 200:
            typer.echo(f"Error: {response.json()}")
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
        typer.echo(f"Error: {e}")
        raise typer.Exit(1)

if __name__ == "__main__":
    app()

