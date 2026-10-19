# API Gateway

Punto de entrada único de LogiTrack. Reenvía las peticiones a Fleet Service y Shipment Service.

## Stack
FastAPI + httpx.

## Levantar en local
1. `python -m venv venv && venv\Scripts\activate`
2. `pip install -r requirements.txt`
3. Copiar `.env.example` a `.env` con las URLs de Fleet Service y Shipment Service corriendo localmente.
4. `uvicorn app.main:app --reload --port 8002`

## Endpoints (proxy)
- `GET /health`
- `GET /api/v1/vehiculos`, `GET /api/v1/vehiculos/{id}`, `POST /api/v1/vehiculos`
- `GET /api/v1/conductores`, `POST /api/v1/conductores`
- `POST /api/v1/envios`, `GET /api/v1/envios`, `GET /api/v1/envios/{id}`, `GET /api/v1/envios/{id}/eventos`, `PATCH /api/v1/envios/{id}/asignar`, `PATCH /api/v1/envios/{id}/estado`, `POST /api/v1/envios/{id}/prueba-entrega`

> Nota: autenticación JWT todavía no está cableada en estas rutas — pendiente de diseño (ver decisión de arquitectura de auth).

## Calentamiento de microservicios (Render)
En Render gratis cada servicio se duerme tras ~15 min sin peticiones y tarda hasta ~1 min en despertar. Para
acortar ese problema, al arrancar el gateway lanza una tarea en segundo plano (`app/calentamiento.py`) que hace
`GET /health` a todos los servicios configurados (`*_SERVICE_URL`) en paralelo, con reintentos y la clave interna
(`X-Internal-Key`). No retrasa el arranque: el gateway responde desde el primer momento.

| Variable | Por defecto | Qué hace |
|---|---|---|
| `WARMUP_ACTIVO` | `true` | `false` lo desactiva |
| `WARMUP_INTENTOS` | `5` | Intentos por servicio |
| `WARMUP_PAUSA_S` | `4` | Segundos entre intentos |
| `WARMUP_TIMEOUT_S` | `15` | Espera máxima de cada intento |
| `WARMUP_INTERVALO_MIN` | `0` | `0` = solo al arrancar; `N` = repetir cada N minutos mientras el gateway esté despierto |
| `WARMUP_SERVICIOS` | vacío | Nombres separados por coma para calentar solo algunos (`fleet,billing`) |

Los resultados se ven en los logs: `[INFO] Enviando ping de calentamiento a ...`, `[SUCCESS] Servicio ... activo`.
