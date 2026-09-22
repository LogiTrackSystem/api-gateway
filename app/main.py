from fastapi import FastAPI
import httpx, os
from dotenv import load_dotenv

load_dotenv()
app = FastAPI(title="API Gateway")

FLEET_SERVICE_URL = os.getenv("FLEET_SERVICE_URL")

@app.get("/health")
def health():
    return {"status": "ok", "service": "api-gateway"}

@app.get("/api/v1/vehiculos")
async def get_vehicles():
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{FLEET_SERVICE_URL}/vehiculos/")
        return resp.json()