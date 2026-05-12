from fastapi import FastAPI
from pydantic import BaseModel
import subprocess
import os

app = FastAPI()

class TaskRequest(BaseModel):
    task: str
    token: str | None = None

@app.post("/run")
def run_task(req: TaskRequest):
    expected = os.getenv("GATEWAY_TOKEN")

    if expected and req.token != expected:
        return {"status": "forbidden"}

    task = req.task.lower()

    if "complex" in task or "build" in task:
        subprocess.Popen([
            "python",
            "run_crewai.py",
            req.task
        ])

        return {
            "status": "started",
            "runner": "crewai"
        }

    subprocess.Popen([
        "python",
        "run_openclaw.py",
        req.task
    ])

    return {
        "status": "started",
        "runner": "openclaw"
    }

@app.get("/health")
def health():
    return {"status": "ok"}
