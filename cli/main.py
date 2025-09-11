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

if __name__ == "__main__":
    app()

