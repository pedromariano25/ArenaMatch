"""Distâncias para o filtro "perto de mim" (sem serviços externos)."""

from decimal import Decimal, InvalidOperation
from math import asin, cos, radians, sin, sqrt

RAIO_DA_TERRA_KM = 6371.0


def distancia_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distância em linha reta entre dois pontos (fórmula de haversine)."""
    dlat, dlng = radians(lat2 - lat1), radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 2 * RAIO_DA_TERRA_KM * asin(sqrt(a))


def ler_coordenadas(latitude: str | None, longitude: str | None) -> tuple[float, float] | None:
    """Coordenadas válidas vindas da query string (``None`` se ausentes ou inválidas)."""
    try:
        lat, lng = float(Decimal(latitude)), float(Decimal(longitude))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if -90 <= lat <= 90 and -180 <= lng <= 180:
        return lat, lng
    return None
