import typer
import requests
from dotenv import load_dotenv
import os

load_dotenv()

app = typer.Typer()

API_URL = os.getenv("API_URL")

if not API_URL:
    raise ValueError("API_URL environment variable is not set")

@app.command()
def register(config: str):
    """Register an app from YAML/JSON spec."""
    with open(config) as f:
        spec = f.read()
    resp = requests.post(f"{API_URL}/apps/register", data=spec)
    typer.echo(resp.json())

@app.command()
def up(name: str):
    """Start the app."""
    resp = requests.post(f"{API_URL}/apps/{name}/up")
    typer.echo(resp.json())

@app.command()
def status(name: str):
    """Check app status."""
    resp = requests.get(f"{API_URL}/apps/{name}/status")
    typer.echo(resp.json())

if __name__ == "__main__":
    app()

