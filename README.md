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