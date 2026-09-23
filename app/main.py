from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import httpx, os
from dotenv import load_dotenv

load_dotenv()
app = FastAPI(title="API Gateway")

# CORS: permite que el frontend (web-frontend) consuma la API desde otro origen
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

FLEET_SERVICE_URL = os.getenv("FLEET_SERVICE_URL")
SHIPMENT_SERVICE_URL = os.getenv("SHIPMENT_SERVICE_URL")


@app.get("/health")
def health():
    return {"status": "ok", "service": "api-gateway"}


# ---------- Vehiculos (Fleet Service) ----------

@app.get("/api/v1/vehiculos")
async def get_vehicles():
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{FLEET_SERVICE_URL}/vehiculos/")
        return resp.json()


@app.get("/api/v1/vehiculos/{vehicle_id}")
async def get_vehicle(vehicle_id: str):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{FLEET_SERVICE_URL}/vehiculos/{vehicle_id}")
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail="Vehículo no encontrado")
        return resp.json()


@app.post("/api/v1/vehiculos", status_code=201)
async def create_vehicle(payload: dict):
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{FLEET_SERVICE_URL}/vehiculos/", json=payload)
        return JSONResponse(status_code=resp.status_code, content=resp.json())


# ---------- Conductores (Fleet Service) ----------

@app.get("/api/v1/conductores")
async def get_drivers():
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{FLEET_SERVICE_URL}/conductores/")
        return resp.json()


@app.post("/api/v1/conductores", status_code=201)
async def create_driver(payload: dict):
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{FLEET_SERVICE_URL}/conductores/", json=payload)
        return JSONResponse(status_code=resp.status_code, content=resp.json())


# ---------- Envios (Shipment Service) ----------

@app.post("/api/v1/envios", status_code=201)
async def create_shipment(payload: dict):
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{SHIPMENT_SERVICE_URL}/envios/", json=payload)
        return JSONResponse(status_code=resp.status_code, content=resp.json())


@app.get("/api/v1/envios")
async def list_shipments(estado: str | None = None, cliente_id: str | None = None):
    params = {k: v for k, v in {"estado": estado, "cliente_id": cliente_id}.items() if v is not None}
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{SHIPMENT_SERVICE_URL}/envios/", params=params)
        return resp.json()


@app.get("/api/v1/envios/{envio_id}")
async def get_shipment(envio_id: str):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{SHIPMENT_SERVICE_URL}/envios/{envio_id}")
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail="Envío no encontrado")
        return resp.json()


@app.get("/api/v1/envios/{envio_id}/eventos")
async def get_shipment_events(envio_id: str):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{SHIPMENT_SERVICE_URL}/envios/{envio_id}/eventos")
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail="Envío no encontrado")
        return resp.json()


@app.patch("/api/v1/envios/{envio_id}/asignar")
async def assign_shipment(envio_id: str, payload: dict):
    async with httpx.AsyncClient() as client:
        resp = await client.patch(f"{SHIPMENT_SERVICE_URL}/envios/{envio_id}/asignar", json=payload)
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail="Envío no encontrado")
        return resp.json()


@app.patch("/api/v1/envios/{envio_id}/estado")
async def update_shipment_status(envio_id: str, payload: dict):
    async with httpx.AsyncClient() as client:
        resp = await client.patch(f"{SHIPMENT_SERVICE_URL}/envios/{envio_id}/estado", json=payload)
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail="Envío no encontrado")
        return resp.json()


@app.post("/api/v1/envios/{envio_id}/prueba-entrega", status_code=201)
async def register_delivery_proof(envio_id: str, payload: dict):
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{SHIPMENT_SERVICE_URL}/envios/{envio_id}/prueba-entrega", json=payload)
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail="Envío no encontrado")
        return JSONResponse(status_code=resp.status_code, content=resp.json())