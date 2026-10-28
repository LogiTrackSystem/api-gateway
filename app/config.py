import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

PREFIJO_API = "/api/v1"
TIMEOUT_LECTURA_S = float(os.getenv("GATEWAY_TIMEOUT_S", "65"))  # crear un envío puede esperar a OSRM
CACHE_OPENAPI_S = 20


# ---------- Calentamiento ("warm-up") de los microservicios ----------
# En Render gratis cada servicio se duerme tras ~15 min sin tráfico. Al arrancar, el gateway les manda un
# ping a /health en segundo plano para que vayan despertando (ver calentamiento.py). Todo es configurable
# por variables de entorno; las URLs salen de SERVICIOS (las mismas *_SERVICE_URL que usa el proxy).
def _entero(nombre: str, defecto: int, minimo: int = 0) -> int:
    try:
        return max(minimo, int(os.getenv(nombre, str(defecto))))
    except ValueError:
        return defecto


def _decimal(nombre: str, defecto: float, minimo: float = 0.0) -> float:
    try:
        return max(minimo, float(os.getenv(nombre, str(defecto))))
    except ValueError:
        return defecto


def _booleano(nombre: str, defecto: bool) -> bool:
    valor = os.getenv(nombre)
    if valor is None:
        return defecto
    return valor.strip().lower() not in {"0", "false", "no", "off", ""}


@dataclass(frozen=True)
class ConfigCalentamiento:
    activo: bool            # WARMUP_ACTIVO (por defecto sí)
    intentos: int           # WARMUP_INTENTOS: intentos por servicio; 0 = sin límite (hasta que responda)
    pausa_s: float          # WARMUP_PAUSA_S: pausa entre intentos (mínimo 1 s si los intentos no tienen límite)
    timeout_s: float        # WARMUP_TIMEOUT_S: espera máxima de cada intento (un servicio dormido puede tardar ~2 min en responder)
    intervalo_min: float    # WARMUP_INTERVALO_MIN: 0 = solo al arrancar; >0 = comprobar cada N minutos mientras el gateway esté despierto (5 por defecto; 10 es la otra opción habitual)
    solo: frozenset[str]    # WARMUP_SERVICIOS: nombres separados por coma (vacío = todos los configurados)
    intentos_periodicos: int = 2  # WARMUP_INTENTOS_PERIODICOS: intentos por comprobación periódica (el 2.º cubre a un servicio que se está despertando)


def config_calentamiento() -> ConfigCalentamiento:
    """Lee la configuración en el momento de la llamada (así las pruebas pueden cambiar el entorno)."""
    solo = frozenset(n.strip().lower() for n in os.getenv("WARMUP_SERVICIOS", "").split(",") if n.strip())
    intentos = _entero("WARMUP_INTENTOS", 0, minimo=0)
    pausa_s = _decimal("WARMUP_PAUSA_S", 5.0)
    if intentos == 0:
        pausa_s = max(pausa_s, 1.0)  # sin límite de intentos: nunca girar en vacío contra un servicio caído
    return ConfigCalentamiento(
        activo=_booleano("WARMUP_ACTIVO", True),
        intentos=intentos,
        pausa_s=pausa_s,
        timeout_s=_decimal("WARMUP_TIMEOUT_S", 30.0, minimo=1.0),
        intervalo_min=_decimal("WARMUP_INTERVALO_MIN", 5.0),
        intentos_periodicos=_entero("WARMUP_INTENTOS_PERIODICOS", 2, minimo=1),
        solo=solo,
    )


def urls_de_salud(servicios: dict[str, str | None], solo: frozenset[str] = frozenset()) -> dict[str, str]:
    """{nombre: URL de /health} de los servicios configurados (y, si se pide, solo de los indicados)."""
    return {
        nombre: f"{base}/health"
        for nombre, base in servicios.items()
        if base and (not solo or nombre in solo)
    }

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
    _r("auth", "shipment", "GET,POST"),
    _r("usuarios", "shipment", "GET,POST,PATCH"),
    _r("vehiculos", "fleet", "GET,POST,PATCH"),
    _r("conductores", "fleet", "GET,POST,PATCH,PUT"),
    _r("viabilidad", "fleet", "POST", destino="/reservas/viabilidad"),  # antes que "reservas": es más específica
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
    _r("facturas-pedido", "billing", "GET"),
    _r("cotizaciones", "billing", "GET"),
    _r("pagos", "billing", "GET,POST"),
    _r("costos-ruta", "billing", "GET"),
    _r("tarifas", "billing", "GET,POST"),
    _r("dashboard", "analytics", "GET"),
    _r("etl", "analytics", "POST"),
]