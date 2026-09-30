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
ROUTING_SERVICE_URL = os.getenv("ROUTING_SERVICE_URL")
TRACKING_SERVICE_URL = os.getenv("TRACKING_SERVICE_URL")
MAINTENANCE_SERVICE_URL = os.getenv("MAINTENANCE_SERVICE_URL")
CUSTOMS_SERVICE_URL = os.getenv("CUSTOMS_SERVICE_URL")
NOTIFICATION_SERVICE_URL = os.getenv("NOTIFICATION_SERVICE_URL")
BILLING_SERVICE_URL = os.getenv("BILLING_SERVICE_URL")
ANALYTICS_SERVICE_URL = os.getenv("ANALYTICS_SERVICE_URL")


@app.get("/health")
def health():
    return {"status": "ok", "service": "api-gateway"}


async def _proxy(method: str, url: str, json_body=None, params=None):
    """Delega una request al microservicio de origen."""

    async with httpx.AsyncClient() as client:
        resp = await client.request(method, url, json=json_body, params=params)
        try:
            content = resp.json()
        except Exception:
            content = resp.text
        return JSONResponse(status_code=resp.status_code, content=content)


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
        print(f"DEBUG -> URL llamada: {FLEET_SERVICE_URL}/vehiculos/{vehicle_id}")
        print(f"DEBUG -> status de Fleet: {resp.status_code}, body: {resp.text}")
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail="Vehículo no encontrado")
        return resp.json()


@app.post("/api/v1/vehiculos", status_code=201)
async def create_vehicle(payload: dict):
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{FLEET_SERVICE_URL}/vehiculos/", json=payload)
        return JSONResponse(status_code=resp.status_code, content=resp.json())


@app.patch("/api/v1/vehiculos/{vehicle_id}/estado")
async def update_vehicle_state(vehicle_id: str, payload: dict):
    return await _proxy("PATCH", f"{FLEET_SERVICE_URL}/vehiculos/{vehicle_id}/estado", json_body=payload)


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


# ---------- Routing Service ----------

@app.get("/api/v1/rutas")
async def listar_rutas(envio_id: str | None = None):
    async with httpx.AsyncClient() as client:
        params = {"envio_id": envio_id} if envio_id else {}
        resp = await client.get(f"{ROUTING_SERVICE_URL}/rutas/", params=params)
    return resp.json()


@app.post("/api/v1/rutas", status_code=201)
async def crear_ruta(payload: dict):
    return await _proxy("POST", f"{ROUTING_SERVICE_URL}/rutas/", json_body=payload)


@app.get("/api/v1/rutas/{ruta_id}")
async def obtener_ruta(ruta_id: str):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{ROUTING_SERVICE_URL}/rutas/{ruta_id}")
    return resp.json()


@app.get("/api/v1/rutas/{ruta_id}/historial")
async def obtener_historial_ruta(ruta_id: str):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{ROUTING_SERVICE_URL}/rutas/{ruta_id}/historial")
    return resp.json()


@app.patch("/api/v1/rutas/{ruta_id}/recalcular")
async def recalcular_ruta(ruta_id: str, payload: dict):
    return await _proxy("PATCH", f"{ROUTING_SERVICE_URL}/rutas/{ruta_id}/recalcular", json_body=payload)


# ---------- Tracking Ingestion Service ----------

@app.post("/api/v1/telemetria", status_code=201)
async def crear_lectura_telemetria(payload: dict):
    return await _proxy("POST", f"{TRACKING_SERVICE_URL}/telemetria/", json_body=payload)


@app.get("/api/v1/telemetria/{vehiculo_id}")
async def obtener_telemetria(vehiculo_id: str, limite: int = 100):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{TRACKING_SERVICE_URL}/telemetria/{vehiculo_id}", params={"limite": limite})
    return resp.json()


# ---------- Maintenance Service ----------

@app.post("/api/v1/programas", status_code=201)
async def crear_programa_mantenimiento(payload: dict):
    return await _proxy("POST", f"{MAINTENANCE_SERVICE_URL}/programas/", json_body=payload)


@app.get("/api/v1/programas/{vehiculo_id}")
async def obtener_programas_mantenimiento(vehiculo_id: str):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{MAINTENANCE_SERVICE_URL}/programas/{vehiculo_id}")
    return resp.json()


@app.post("/api/v1/intervenciones", status_code=201)
async def crear_intervencion_mantenimiento(payload: dict):
    return await _proxy("POST", f"{MAINTENANCE_SERVICE_URL}/intervenciones/", json_body=payload)


@app.get("/api/v1/intervenciones/{vehiculo_id}")
async def obtener_intervenciones(vehiculo_id: str):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{MAINTENANCE_SERVICE_URL}/intervenciones/{vehiculo_id}")
    return resp.json()


# ---------- Customs Service ----------

@app.get("/api/v1/declaraciones")
async def listar_declaraciones(estado: str | None = None):
    async with httpx.AsyncClient() as client:
        params = {"estado": estado} if estado else {}
        resp = await client.get(f"{CUSTOMS_SERVICE_URL}/declaraciones/", params=params)
    return resp.json()


@app.get("/api/v1/declaraciones/{envio_id}")
async def obtener_declaracion(envio_id: str):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{CUSTOMS_SERVICE_URL}/declaraciones/{envio_id}")
    return resp.json()


@app.patch("/api/v1/declaraciones/{declaracion_id}/estado")
async def actualizar_estado_declaracion(declaracion_id: str, payload: dict):
    return await _proxy("PATCH", f"{CUSTOMS_SERVICE_URL}/declaraciones/{declaracion_id}/estado", json_body=payload)


# ---------- Notification Service ----------

@app.get("/api/v1/notificaciones")
async def listar_notificaciones(limite: int = 50):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{NOTIFICATION_SERVICE_URL}/notificaciones/", params={"limite": limite})
    return resp.json()


@app.get("/api/v1/preferencias/{cliente_id}")
async def obtener_preferencia(cliente_id: str):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{NOTIFICATION_SERVICE_URL}/preferencias/{cliente_id}")
    return resp.json()


@app.post("/api/v1/preferencias/{cliente_id}")
async def configurar_preferencia(cliente_id: str, payload: dict):
    return await _proxy("POST", f"{NOTIFICATION_SERVICE_URL}/preferencias/{cliente_id}", json_body=payload)


# ---------- Billing Service ----------

@app.get("/api/v1/facturas")
async def listar_facturas(cliente_id: str | None = None, periodo: str | None = None, estado: str | None = None):
    params = {k: v for k, v in {"cliente_id": cliente_id, "periodo": periodo, "estado": estado}.items() if v}
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{BILLING_SERVICE_URL}/facturas/", params=params)
    return resp.json()


@app.post("/api/v1/facturas/cerrar-periodo")
async def cerrar_periodo_facturacion():
    return await _proxy("POST", f"{BILLING_SERVICE_URL}/facturas/cerrar-periodo")


@app.get("/api/v1/costos-ruta")
async def listar_costos_ruta(envio_id: str | None = None):
    params = {"envio_id": envio_id} if envio_id else {}
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{BILLING_SERVICE_URL}/costos-ruta/", params=params)
    return resp.json()


@app.post("/api/v1/tarifas", status_code=201)
async def configurar_tarifa(payload: dict):
    return await _proxy("POST", f"{BILLING_SERVICE_URL}/tarifas/", json_body=payload)


@app.get("/api/v1/tarifas/{cliente_id}")
async def obtener_tarifa(cliente_id: str):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{BILLING_SERVICE_URL}/tarifas/{cliente_id}")
    return resp.json()


# ---------- Analytics Service ----------

@app.get("/api/v1/analytics/resumen")
async def analytics_resumen():
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{ANALYTICS_SERVICE_URL}/dashboard/resumen")
    return resp.json()


@app.get("/api/v1/analytics/entregas-diarias")
async def analytics_entregas_diarias(dias: int = 30):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{ANALYTICS_SERVICE_URL}/dashboard/entregas-diarias", params={"dias": dias})
    return resp.json()


@app.get("/api/v1/analytics/utilizacion-flota")
async def analytics_utilizacion_flota():
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{ANALYTICS_SERVICE_URL}/dashboard/utilizacion-flota")
    return resp.json()


@app.get("/api/v1/analytics/costo-por-km")
async def analytics_costo_por_km():
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{ANALYTICS_SERVICE_URL}/dashboard/costo-por-km")
    return resp.json()


@app.get("/api/v1/analytics/eficiencia-combustible")
async def analytics_eficiencia_combustible(limite: int = 50):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{ANALYTICS_SERVICE_URL}/dashboard/eficiencia-combustible", params={"limite": limite})
    return resp.json()


@app.get("/api/v1/analytics/proyeccion-mantenimiento")
async def analytics_proyeccion_mantenimiento(dias: int = 90):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{ANALYTICS_SERVICE_URL}/dashboard/proyeccion-mantenimiento", params={"dias": dias})
    return resp.json()


@app.get("/api/v1/analytics/actividad-reciente")
async def analytics_actividad_reciente(limite: int = 20):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{ANALYTICS_SERVICE_URL}/dashboard/actividad-reciente", params={"limite": limite})
    return resp.json()


@app.post("/api/v1/analytics/etl")
async def analytics_etl_ejecutar():
    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(f"{ANALYTICS_SERVICE_URL}/etl/ejecutar")
        try:
            content = resp.json()
        except Exception:
            content = resp.text
        return JSONResponse(status_code=resp.status_code, content=content)