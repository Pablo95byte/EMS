"""Fase 2 - Forecast solare da Open-Meteo.

Usa la variabile `global_tilted_irradiance` (GTI) calcolata da Open-Meteo per
il piano dei moduli (tilt/azimuth), poi stima la potenza AC attesa come:

    P_ac [W] = kWp * 1000 * (GTI / 1000 W/m2) * performance_ratio
"""

from __future__ import annotations

import logging
from datetime import date, datetime

import requests

from hems.config import PlantConfig
from hems.db.database import Database

log = logging.getLogger(__name__)

API_URL = "https://api.open-meteo.com/v1/forecast"


def fetch_solar_forecast(
    plant: PlantConfig, target_day: date, timeout_s: float = 30.0
) -> dict[datetime, float]:
    """Ritorna {ora locale -> potenza AC prevista in W} per il giorno target."""
    params = {
        "latitude": plant.latitude,
        "longitude": plant.longitude,
        "hourly": "global_tilted_irradiance",
        "tilt": plant.tilt_deg,
        "azimuth": plant.azimuth_deg,
        "timezone": "auto",
        "start_date": target_day.isoformat(),
        "end_date": target_day.isoformat(),
    }
    response = requests.get(API_URL, params=params, timeout=timeout_s)
    response.raise_for_status()
    payload = response.json()

    times = payload["hourly"]["time"]
    gti_values = payload["hourly"]["global_tilted_irradiance"]

    forecast: dict[datetime, float] = {}
    for iso_time, gti in zip(times, gti_values):
        gti_wm2 = float(gti) if gti is not None else 0.0
        power_w = plant.kwp * 1000.0 * (gti_wm2 / 1000.0) * plant.performance_ratio
        forecast[datetime.fromisoformat(iso_time)] = round(power_w, 1)
    return forecast


def store_solar_forecast(
    db: Database, plant: PlantConfig, target_day: date
) -> int:
    forecast = fetch_solar_forecast(plant, target_day)
    for hour, power_w in forecast.items():
        db.upsert_pianificazione(hour, produzione_solare_prevista_w=power_w)
    total_kwh = sum(forecast.values()) / 1000.0
    log.info(
        "Forecast solare %s: %d ore, %.1f kWh attesi", target_day, len(forecast),
        total_kwh,
    )
    return len(forecast)
