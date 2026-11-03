"""Configuración común de las pruebas.

El calentamiento de microservicios (app/calentamiento.py) se desactiva por defecto en las pruebas para que
ninguna prueba haga llamadas de red al arrancar el gateway. Las pruebas de test_calentamiento.py lo activan
explícitamente cuando lo necesitan.
"""
import os
import sys

os.environ.setdefault("WARMUP_ACTIVO", "false")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
