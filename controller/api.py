from fastapi import FastAPI
from .manager import AppManager
from .state import StateStore

app = FastAPI()
manager = AppManager()
store = StateStore("autoscaler.db")

@app.post("/apps/register")
def register_app(spec: dict):
    return manager.register(spec)

@app.post("/apps/{name}/up")
def app_up(name: str):
    return manager.start(name)

@app.get("/apps/{name}/status")
def app_status(name: str):
    return manager.status(name)

