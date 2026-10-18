"""Autenticación y permisos por rol del API Gateway.

- El gateway verifica el token Bearer (firmado por Shipment en POST /auth/login) sin consultar a nadie.
- Quita cualquier cabecera X-User-* que venga del exterior e inyecta la identidad verificada
  (X-User-Id, X-User-Rol, X-Cliente-Id) para que los servicios apliquen la propiedad del recurso.
- La tabla REGLAS decide qué rol puede usar cada ruta. Gana la primera que coincida; lo que no
  aparece se deniega (403). Los permisos de endpoints que se agregan en bloques posteriores
  (cotizar, programados, cancelar, pagos...) ya están declarados aquí.
"""
import os
import re
from dataclasses import dataclass
from typing import Optional

from .jwt_simple import TokenError, verificar_token

C, O, G, A = "cliente", "operador", "gestor_flota", "administrador"
TODOS = frozenset({C, O, G, A})
PERSONAL = frozenset({O, G, A})          # personal interno (todo menos cliente)

CABECERAS_IDENTIDAD = ("x-user-id", "x-user-rol", "x-cliente-id")


@dataclass(frozen=True)
class Identidad:
    usuario_id: str
    rol: str
    cliente_id: Optional[str]
    nombre: str = ""


@dataclass(frozen=True)
class Regla:
    metodos: frozenset
    patron: "re.Pattern"
    roles: Optional[frozenset]            # None = ruta pública (sin token)
    forzar_query_cliente: bool = False    # para el rol cliente: reescribe ?cliente_id= con el suyo
    cliente_en_ruta: bool = False         # para el rol cliente: el id de la ruta debe ser el suyo


def _p(metodos: str, patron: str, roles, **extra) -> Regla:
    return Regla(
        metodos=frozenset(m.strip().upper() for m in metodos.split(",")),
        patron=re.compile("^" + patron + "$"),
        roles=None if roles is None else frozenset(roles),
        **extra,
    )


ID = r"[^/]+"

# Rutas tal como las ve el frontend, después de /api/v1 y sin barra final.
REGLAS = [
    # --- Identidad ---
    _p("POST", r"/auth/login", None),
    _p("GET", r"/auth/me", TODOS),
    _p("GET,POST,PATCH", rf"/usuarios(/{ID})?", {A}),
    # --- Clientes y ubicaciones ---
    _p("GET", rf"/clientes(/.*)?", {C, O, A}),
    _p("POST,PATCH", rf"/clientes(/{ID})?", {O, A}),
    _p("GET", r"/ubicaciones(/.*)?", TODOS),
    _p("POST,PATCH", r"/ubicaciones(/.*)?", {O, A}),
    _p("GET", r"/rutas-maestras(/.*)?", PERSONAL),
    _p("POST", r"/rutas-maestras(/.*)?", {O, A}),
    # --- Cotización, viabilidad y envíos ---
    _p("POST", r"/viabilidad", {C, O, A}),
    _p("POST", r"/envios/cotizar", {C, O, A}),
    _p("GET", r"/envios/programados", PERSONAL),
    _p("POST", r"/envios", {C, O, A}),
    _p("GET", r"/envios(/.*)?", TODOS),
    _p("POST", rf"/envios/{ID}/cancelar", {G, A}),
    _p("PATCH", rf"/envios/{ID}/reprogramar", {G, A}),
    _p("POST", rf"/envios/{ID}/reintentar-asignacion", PERSONAL),
    _p("PATCH", rf"/envios/{ID}/estado", PERSONAL),
    _p("POST", rf"/envios/{ID}/prueba-entrega", {O, A}),
    # --- Pagos, cotizaciones y reembolsos (bloques de facturación) ---
    _p("GET", r"/cotizaciones(/.*)?", {C, O, A}, forzar_query_cliente=True),
    _p("GET", r"/pagos/por-reembolsar", {A}),
    _p("GET", r"/pagos(/.*)?", {C, O, A}, forzar_query_cliente=True),
    _p("POST", rf"/pagos/{ID}/reembolsar", {A}),
    _p("GET", r"/facturas-pedido(/.*)?", {C, A}, forzar_query_cliente=True),
    # --- Flota y mantenimiento ---
    _p("GET", r"/(vehiculos|conductores|reservas)(/.*)?", PERSONAL),
    _p("POST,PATCH,PUT", r"/(vehiculos|conductores)(/.*)?", {G, A}),
    _p("POST", r"/asignaciones(/.*)?", {O, A}),
    _p("GET", r"/rutas(/.*)?", PERSONAL),
    _p("PATCH", r"/rutas(/.*)?", PERSONAL),
    _p("GET", r"/(programas|intervenciones)(/.*)?", PERSONAL),
    _p("POST", r"/(programas|intervenciones)(/.*)?", {G, A}),
    # --- Seguimiento (nunca para el cliente) ---
    _p("GET", r"/(seguimiento|simulaciones|telemetria)(/.*)?", PERSONAL),
    # --- Aduanas ---
    _p("GET,PATCH", r"/declaraciones(/.*)?", {O, A}),
    # --- Notificaciones ---
    # Las notificaciones aún no guardan a qué cliente pertenecen, por eso el cliente no las lista
    # (se abrirá cuando exista el filtro por cliente).
    _p("GET", r"/notificaciones(/.*)?", {O, A}),
    _p("GET,POST", rf"/preferencias/{ID}", {C, A}, cliente_en_ruta=True),
    # --- Facturación (solo administración, salvo las facturas propias del cliente) ---
    _p("GET", r"/facturas(/.*)?", {C, A}, forzar_query_cliente=True),
    _p("POST", r"/facturas/cerrar-periodo", {A}),
    _p("GET,POST", r"/(tarifas|costos-ruta)(/.*)?", {A}),
    # --- Analítica ---
    _p("GET", r"/dashboard/(utilizacion-flota|proyeccion-mantenimiento)", {G, A}),
    _p("GET", r"/dashboard(/.*)?", {A}),
    _p("POST", r"/etl(/.*)?", {A}),
    # --- Estado de los servicios ---
    _p("GET", r"/estado", {A}),
]


def buscar_regla(metodo: str, ruta: str) -> Optional[Regla]:
    ruta = ruta.rstrip("/") or "/"
    metodo = metodo.upper()
    for regla in REGLAS:
        if metodo in regla.metodos and regla.patron.match(ruta):
            return regla
    return None


class ErrorAcceso(Exception):
    def __init__(self, status: int, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.status, self.codigo, self.mensaje = status, codigo, mensaje


def _secreto() -> str:
    valor = os.getenv("JWT_SECRET", "").strip()
    if len(valor) < 16:
        raise ErrorAcceso(503, "JWT_NO_CONFIGURADO", "Falta JWT_SECRET (mínimo 16 caracteres) en el gateway")
    return valor


def identificar(authorization: Optional[str]) -> Identidad:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ErrorAcceso(401, "NO_AUTENTICADO", "Inicie sesión: falta la cabecera Authorization: Bearer <token>")
    try:
        datos = verificar_token(authorization[7:].strip(), _secreto())
    except TokenError as exc:
        raise ErrorAcceso(401, exc.codigo, exc.mensaje)
    if not datos.get("sub") or datos.get("rol") not in TODOS:
        raise ErrorAcceso(401, "TOKEN_INVALIDO", "El token no contiene una identidad válida")
    return Identidad(
        usuario_id=str(datos["sub"]), rol=datos["rol"],
        cliente_id=datos.get("cliente_id"), nombre=datos.get("nombre", ""),
    )


def autorizar(metodo: str, ruta: str, authorization: Optional[str]):
    """Devuelve (regla, identidad|None). Lanza ErrorAcceso (401/403) si no procede.
    Una ruta que no coincide con ninguna regla devuelve (None, None) y el proxy responde 404/405."""
    regla = buscar_regla(metodo, ruta)
    if regla is None:
        return None, None
    if regla.roles is None:
        return regla, None
    ident = identificar(authorization)
    if ident.rol not in regla.roles:
        raise ErrorAcceso(403, "SIN_PERMISO", f"El rol '{ident.rol}' no tiene permiso para esta operación")
    if ident.rol == C and not ident.cliente_id:
        raise ErrorAcceso(403, "SIN_PERMISO", "La cuenta de cliente no está ligada a un cliente")
    if ident.rol == C and regla.cliente_en_ruta:
        id_ruta = ruta.rstrip("/").split("/")[-1].lower()
        if id_ruta != str(ident.cliente_id).lower():
            raise ErrorAcceso(403, "SIN_PERMISO", "Solo puede consultar la información de su propio cliente")
    return regla, ident


def cabeceras_identidad(ident: Optional[Identidad]) -> dict:
    if ident is None:
        return {}
    out = {"x-user-id": ident.usuario_id, "x-user-rol": ident.rol}
    if ident.cliente_id:
        out["x-cliente-id"] = str(ident.cliente_id)
    return out
