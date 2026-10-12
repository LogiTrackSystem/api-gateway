import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

PREFIJO_API = "/api/v1"
TIMEOUT_LECTURA_S = float(os.getenv("GATEWAY_TIMEOUT_S", "65"))  # crear un envío puede esperar a OSRM
CACHE_OPENAPI_S = 20

# Orígenes del frontend autorizados a llamar al gateway (lista separada por comas).
# Si la variable no existe se usan los puertos habituales de desarrollo; "*" abre el acceso a todos.
CORS_POR_DEFECTO = "http://localhost:5173,http://localhost:3000,http://localhost:4200"


def origenes_cors() -> list[str]:
    crudo = os.getenv("CORS_ORIGINS", CORS_POR_DEFECTO)
    return [o.strip().rstrip("/") for o in crudo.split(",") if o.strip()]


def _url(nombre: str):
    valor = os.getenv(nombre)
    return valor.strip().rstrip("/") if valor else None


SERVICIOS = {
    "fleet": _url("FLEET_SERVICE_URL"),
    "shipment": _url("SHIPMENT_SERVICE_URL"),
    "routing": _url("ROUTING_SERVICE_URL"),
    "tracking": _url("TRACKING_SERVICE_URL"),
    "maintenance": _url("MAINTENANCE_SERVICE_URL"),
    "customs": _url("CUSTOMS_SERVICE_URL"),
    "notification": _url("NOTIFICATION_SERVICE_URL"),
    "billing": _url("BILLING_SERVICE_URL"),
    "analytics": _url("ANALYTICS_SERVICE_URL"),
}


@dataclass(frozen=True)
class Ruta:
    prefijo: str      # lo que ve el frontend, después de /api/v1
    servicio: str     # a qué microservicio se reenvía
    destino: str      # prefijo equivalente dentro del microservicio
    metodos: frozenset


def _r(prefijo: str, servicio: str, metodos: str, destino: str | None = None) -> Ruta:
    return Ruta(
        prefijo=prefijo,
        servicio=servicio,
        destino=destino or f"/{prefijo}",
        metodos=frozenset(m.strip().upper() for m in metodos.split(",")),
    )


# Superficie pública de la API. Lo que no aparece aquí (por ejemplo POST /reservas de Fleet o
# POST /telemetria de Tracking, que son de uso interno) no se puede alcanzar desde afuera.
RUTAS = [
    _r("vehiculos", "fleet", "GET,POST,PATCH"),
    _r("conductores", "fleet", "GET,POST,PATCH,PUT"),
    _r("reservas", "fleet", "GET"),
    _r("clientes", "shipment", "GET,POST,PATCH"),
    _r("envios", "shipment", "GET,POST,PATCH"),
    _r("ubicaciones", "routing", "GET,POST,PATCH"),
    _r("rutas-maestras", "routing", "GET,POST"),
    _r("asignaciones", "routing", "POST"),
    _r("rutas", "routing", "GET,PATCH"),
    _r("seguimiento", "tracking", "GET"),
    _r("simulaciones", "tracking", "GET"),
    _r("telemetria", "tracking", "GET"),
    _r("programas", "maintenance", "GET,POST"),
    _r("intervenciones", "maintenance", "GET,POST"),
    _r("declaraciones", "customs", "GET,PATCH"),
    _r("notificaciones", "notification", "GET"),
    _r("preferencias", "notification", "GET,POST"),
    _r("facturas", "billing", "GET,POST"),
    _r("costos-ruta", "billing", "GET"),
    _r("tarifas", "billing", "GET,POST"),
    _r("dashboard", "analytics", "GET"),
    _r("etl", "analytics", "POST"),
]