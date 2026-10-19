"""Calentamiento ("warm-up") de los microservicios cuando el gateway arranca.

Render (plan gratis) duerme cada servicio tras ~15 minutos sin peticiones y tarda entre 15 y 60 segundos
en volver a levantarlo. Si la primera petición real de un usuario cae sobre un servicio dormido, falla
(timeout o 502). Para acortar ese problema, apenas arranca el gateway lanzamos una tarea en segundo plano
que le hace ping a /health de todos los servicios a la vez, con reintentos, para que despierten mientras
el gateway ya atiende peticiones.

- No bloquea el arranque: se lanza con asyncio.create_task dentro del lifespan.
- Usa su propio httpx.AsyncClient con la clave interna (X-Internal-Key), igual que el resto de llamadas
  del gateway a los servicios.
- Las URLs salen de config.SERVICIOS (las variables *_SERVICE_URL), sin duplicar listas.
- Nunca levanta excepciones hacia afuera: un servicio que no responde solo queda registrado en el log.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass

import httpx

from .config import SERVICIOS, ConfigCalentamiento, config_calentamiento, urls_de_salud
from .interno import cabeceras_internas

NIVEL_SUCCESS = 25  # entre INFO (20) y WARNING (30)
logging.addLevelName(NIVEL_SUCCESS, "SUCCESS")
log = logging.getLogger("logitrack.warmup")


@dataclass(frozen=True)
class ResultadoCalentamiento:
    servicio: str
    activo: bool      # True si el servicio respondió (aunque sea con un 4xx: está despierto)
    intentos: int     # intentos que hizo
    ms: int           # milisegundos desde el primer intento hasta el resultado
    detalle: str      # "HTTP 200", último error, etc.


def _preparar_logging() -> None:
    """uvicorn solo configura sus propios loggers: sin esto los INFO de este módulo no saldrían en consola.
    Si la aplicación ya tiene un logging configurado (o pytest), no se toca nada."""
    if log.handlers or logging.getLogger().handlers:
        return
    manejador = logging.StreamHandler()
    manejador.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    log.addHandler(manejador)
    log.setLevel(logging.INFO)
    log.propagate = False


def _descripcion(exc: Exception) -> str:
    texto = str(exc)
    return f"{type(exc).__name__}: {texto}" if texto else type(exc).__name__


async def calentar_servicio(
    cliente: httpx.AsyncClient,
    servicio: str,
    url: str,
    *,
    intentos: int,
    pausa_s: float,
) -> ResultadoCalentamiento:
    """Hace GET a `url` hasta `intentos` veces, con `pausa_s` segundos entre intentos."""
    inicio = time.perf_counter()
    detalle = "sin intentos"
    hechos = 0
    for n in range(1, max(1, intentos) + 1):
        hechos = n
        log.info("Enviando ping de calentamiento a %s (intento %d/%d): %s", servicio, n, intentos, url)
        try:
            resp = await cliente.get(url)
        except Exception as exc:  # RequestError, timeouts, errores de DNS/TLS... (CancelledError no entra aquí)
            detalle = _descripcion(exc)
            log.warning("Servicio %s aún no responde (intento %d/%d): %s", servicio, n, intentos, detalle)
        else:
            ms = round((time.perf_counter() - inicio) * 1000)
            detalle = f"HTTP {resp.status_code}"
            if resp.status_code == 200:
                log.log(NIVEL_SUCCESS, "Servicio %s activo (%d ms, intento %d/%d)", servicio, ms, n, intentos)
                return ResultadoCalentamiento(servicio, True, n, ms, detalle)
            if 400 <= resp.status_code < 500:
                # Respondió: el contenedor ya está despierto. Reintentar no arregla un 4xx (ruta o clave mal puestas).
                log.warning("Servicio %s despierto, pero /health respondió %s; no se reintenta", servicio, detalle)
                return ResultadoCalentamiento(servicio, True, n, ms, detalle)
            # 5xx (p. ej. 502/503 mientras Render levanta el contenedor): se reintenta
            log.warning("Servicio %s respondió %s (intento %d/%d); sigue levantando", servicio, detalle, n, intentos)
        if n < intentos:
            await asyncio.sleep(pausa_s)
    ms = round((time.perf_counter() - inicio) * 1000)
    log.error("Servicio %s no respondió tras %d intento(s): %s", servicio, hechos, detalle)
    return ResultadoCalentamiento(servicio, False, hechos, ms, detalle)


async def ejecutar(
    config: ConfigCalentamiento | None = None,
    servicios: dict[str, str | None] | None = None,
    cliente: httpx.AsyncClient | None = None,
) -> list[ResultadoCalentamiento]:
    """Calienta todos los servicios en paralelo. Con WARMUP_INTERVALO_MIN > 0 repite cada N minutos
    (solo mientras el gateway esté despierto); en otro caso termina tras la primera ronda."""
    _preparar_logging()
    config = config or config_calentamiento()
    urls = urls_de_salud(SERVICIOS if servicios is None else servicios, config.solo)
    if not urls:
        log.info("Calentamiento omitido: no hay microservicios configurados (*_SERVICE_URL)")
        return []

    propio = cliente is None
    if propio:
        cliente = httpx.AsyncClient(
            headers=cabeceras_internas(),
            timeout=httpx.Timeout(config.timeout_s),
            follow_redirects=True,
        )
    try:
        while True:
            log.info("Iniciando calentamiento de %d microservicio(s): %s", len(urls), ", ".join(urls))
            resultados = list(await asyncio.gather(*[
                calentar_servicio(cliente, nombre, url, intentos=config.intentos, pausa_s=config.pausa_s)
                for nombre, url in urls.items()
            ]))
            activos = sum(r.activo for r in resultados)
            nivel = NIVEL_SUCCESS if activos == len(resultados) else logging.WARNING
            log.log(nivel, "Calentamiento terminado: %d/%d servicio(s) activos", activos, len(resultados))
            if config.intervalo_min <= 0:
                return resultados
            await asyncio.sleep(config.intervalo_min * 60)
    finally:
        if propio:
            await cliente.aclose()


async def _sin_excepciones(corrutina) -> list[ResultadoCalentamiento]:
    """La tarea corre sola (nadie hace await de su resultado): una excepción inesperada solo se registra."""
    try:
        return await corrutina
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("El calentamiento de microservicios terminó con un error inesperado")
        return []


def iniciar(
    config: ConfigCalentamiento | None = None,
    servicios: dict[str, str | None] | None = None,
    cliente: httpx.AsyncClient | None = None,
) -> asyncio.Task[list[ResultadoCalentamiento]] | None:
    """Lanza el calentamiento en segundo plano y devuelve de inmediato (fire-and-forget).
    Debe llamarse con el event loop corriendo (dentro del lifespan). Guarda la tarea: si nadie
    mantiene una referencia, Python puede recolectarla antes de que termine."""
    config = config or config_calentamiento()
    if not config.activo:
        _preparar_logging()
        log.info("Calentamiento de microservicios desactivado (WARMUP_ACTIVO)")
        return None
    return asyncio.create_task(
        _sin_excepciones(ejecutar(config, servicios, cliente)), name="warmup-microservicios"
    )


async def detener(tarea: asyncio.Task | None) -> None:
    """Cancela el calentamiento si sigue corriendo (apagado del gateway) y espera a que termine."""
    if tarea is None:
        return
    if not tarea.done():
        tarea.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await tarea
