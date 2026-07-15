"""Caricamento e validazione della configurazione YAML."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATHS = [
    Path("config/config.yaml"),
    Path("config/config.example.yaml"),
]

# Limite hardware: la dongle Huawei puo' crashare con polling < 10 s.
HARD_MIN_POLL_INTERVAL_S = 10


@dataclasses.dataclass(frozen=True)
class InverterConfig:
    host: str
    port: int = 502
    slave_id: int = 1
    connect_timeout_s: float = 10.0
    min_poll_interval_s: float = HARD_MIN_POLL_INTERVAL_S


@dataclasses.dataclass(frozen=True)
class PlantConfig:
    latitude: float
    longitude: float
    tilt_deg: float
    azimuth_deg: float
    kwp: float
    performance_ratio: float = 0.85


@dataclasses.dataclass(frozen=True)
class BatteryConfig:
    capacity_kwh: float
    max_charge_w: float
    max_discharge_w: float
    soc_floor_perc: float = 15.0
    soc_ceiling_perc: float = 100.0
    roundtrip_efficiency: float = 0.90


@dataclasses.dataclass(frozen=True)
class GmeConfig:
    zone: str = "PUN"
    xml_dir: str = "data/gme"
    download_url_template: str = ""


@dataclasses.dataclass(frozen=True)
class OptimizerConfig:
    night_hours: tuple[int, ...] = (2, 3, 4)
    peak_hours: tuple[int, ...] = (19, 20, 21)
    night_price_ratio: float = 0.40
    low_solar_day_kwh: float = 8.0
    forced_charge_w: int = 3000
    max_grid_power_w: int = 4000


@dataclasses.dataclass(frozen=True)
class ControlConfig:
    loop_interval_s: float = 30.0
    dry_run: bool = True


@dataclasses.dataclass(frozen=True)
class Config:
    inverter: InverterConfig
    plant: PlantConfig
    battery: BatteryConfig
    gme: GmeConfig
    optimizer: OptimizerConfig
    control: ControlConfig
    db_path: str = "data/hems.sqlite3"
    telemetry_poll_interval_s: float = 60.0


def _section(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key) or {}
    if not isinstance(value, dict):
        raise ValueError(f"Sezione di configurazione '{key}' non valida")
    return value


def load_config(path: str | Path | None = None) -> Config:
    """Carica la configurazione da YAML applicando i limiti di sicurezza."""
    if path is not None:
        candidates = [Path(path)]
    else:
        candidates = DEFAULT_CONFIG_PATHS
    for candidate in candidates:
        if candidate.exists():
            raw = yaml.safe_load(candidate.read_text()) or {}
            break
    else:
        raise FileNotFoundError(
            f"Nessun file di configurazione trovato tra: {[str(c) for c in candidates]}"
        )

    inv = _section(raw, "inverter")
    inverter = InverterConfig(
        host=inv["host"],
        port=int(inv.get("port", 502)),
        slave_id=int(inv.get("slave_id", 1)),
        connect_timeout_s=float(inv.get("connect_timeout_s", 10)),
        min_poll_interval_s=max(
            float(inv.get("min_poll_interval_s", HARD_MIN_POLL_INTERVAL_S)),
            HARD_MIN_POLL_INTERVAL_S,
        ),
    )

    plant_raw = _section(raw, "plant")
    plant = PlantConfig(
        latitude=float(plant_raw["latitude"]),
        longitude=float(plant_raw["longitude"]),
        tilt_deg=float(plant_raw.get("tilt_deg", 30)),
        azimuth_deg=float(plant_raw.get("azimuth_deg", 0)),
        kwp=float(plant_raw["kwp"]),
        performance_ratio=float(plant_raw.get("performance_ratio", 0.85)),
    )

    batt_raw = _section(raw, "battery")
    battery = BatteryConfig(
        capacity_kwh=float(batt_raw["capacity_kwh"]),
        max_charge_w=float(batt_raw.get("max_charge_w", 5000)),
        max_discharge_w=float(batt_raw.get("max_discharge_w", 5000)),
        soc_floor_perc=float(batt_raw.get("soc_floor_perc", 15.0)),
        soc_ceiling_perc=float(batt_raw.get("soc_ceiling_perc", 100.0)),
        roundtrip_efficiency=float(batt_raw.get("roundtrip_efficiency", 0.90)),
    )

    gme_raw = _section(raw, "gme")
    gme = GmeConfig(
        zone=str(gme_raw.get("zone", "PUN")),
        xml_dir=str(gme_raw.get("xml_dir", "data/gme")),
        download_url_template=str(gme_raw.get("download_url_template", "")),
    )

    opt_raw = _section(raw, "optimizer")
    optimizer = OptimizerConfig(
        night_hours=tuple(int(h) for h in opt_raw.get("night_hours", (2, 3, 4))),
        peak_hours=tuple(int(h) for h in opt_raw.get("peak_hours", (19, 20, 21))),
        night_price_ratio=float(opt_raw.get("night_price_ratio", 0.40)),
        low_solar_day_kwh=float(opt_raw.get("low_solar_day_kwh", 8.0)),
        forced_charge_w=int(opt_raw.get("forced_charge_w", 3000)),
        max_grid_power_w=int(opt_raw.get("max_grid_power_w", 4000)),
    )

    ctrl_raw = _section(raw, "control")
    control = ControlConfig(
        loop_interval_s=max(
            float(ctrl_raw.get("loop_interval_s", 30)), inverter.min_poll_interval_s
        ),
        dry_run=bool(ctrl_raw.get("dry_run", True)),
    )

    tele_raw = _section(raw, "telemetry")
    poll = max(
        float(tele_raw.get("poll_interval_s", 60)), inverter.min_poll_interval_s
    )

    db_raw = _section(raw, "database")

    return Config(
        inverter=inverter,
        plant=plant,
        battery=battery,
        gme=gme,
        optimizer=optimizer,
        control=control,
        db_path=str(db_raw.get("path", "data/hems.sqlite3")),
        telemetry_poll_interval_s=poll,
    )
