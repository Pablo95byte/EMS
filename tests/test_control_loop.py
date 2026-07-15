"""Test del control loop con un client Modbus finto (nessun hardware)."""

from datetime import datetime

import pytest

from hems.config import (
    BatteryConfig,
    Config,
    ControlConfig,
    GmeConfig,
    InverterConfig,
    OptimizerConfig,
    PlantConfig,
)
from hems.control.control_loop import ControlLoop
from hems.db.database import ComandoStrategico, Database
from hems.modbus import registers as regs


class FakeClient:
    def __init__(self, soc: float = 80.0):
        self.soc = soc
        self.writes: list[tuple[int, int]] = []
        self.fallback_called = False

    def read_register(self, register):
        assert register is regs.BATTERY_SOC
        return self.soc

    def write_register(self, register, value):
        self.writes.append((register.address, value))

    def fallback_to_self_consumption(self):
        self.fallback_called = True

    def close(self):
        pass


def _config(dry_run: bool = False) -> Config:
    return Config(
        inverter=InverterConfig(host="127.0.0.1"),
        plant=PlantConfig(latitude=45.0, longitude=9.0, tilt_deg=30, azimuth_deg=0, kwp=6.0),
        battery=BatteryConfig(
            capacity_kwh=10, max_charge_w=5000, max_discharge_w=5000, soc_floor_perc=15.0
        ),
        gme=GmeConfig(),
        optimizer=OptimizerConfig(forced_charge_w=3000, max_grid_power_w=4000),
        control=ControlConfig(loop_interval_s=30, dry_run=dry_run),
        db_path=":memory:",
    )


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.sqlite3")
    yield database
    database.close()


def test_scarica_massima_scrive_registro_forzatura(db):
    now = datetime(2026, 3, 10, 19, 15)
    db.upsert_pianificazione(now, comando_strategico=ComandoStrategico.SCARICA_MASSIMA)
    client = FakeClient(soc=80.0)
    loop = ControlLoop(_config(), client, db)

    result = loop.step(now)

    assert result is ComandoStrategico.SCARICA_MASSIMA
    assert (regs.FORCE_COMMAND.address, 2) in client.writes


def test_protezione_soc_blocca_la_scarica(db):
    now = datetime(2026, 3, 10, 19, 15)
    db.upsert_pianificazione(now, comando_strategico=ComandoStrategico.SCARICA_MASSIMA)
    client = FakeClient(soc=12.0)  # sotto la soglia del 15%
    loop = ControlLoop(_config(), client, db)

    result = loop.step(now)

    assert result is ComandoStrategico.IDLE
    assert (regs.FORCE_COMMAND.address, 2) not in client.writes
    assert (regs.FORCE_COMMAND.address, 0) in client.writes


def test_forzatura_rete_imposta_potenze_e_abilita_carica(db):
    now = datetime(2026, 3, 10, 3, 0)
    db.upsert_pianificazione(now, comando_strategico=ComandoStrategico.FORZATURA_RETE)
    client = FakeClient()
    loop = ControlLoop(_config(), client, db)

    loop.step(now)

    assert (regs.MAX_GRID_POWER.address, 4000) in client.writes
    assert (regs.FORCED_CHARGE_POWER.address, 3000) in client.writes
    assert (regs.GRID_CHARGE_ENABLE.address, 1) in client.writes
    assert (regs.FORCE_COMMAND.address, 1) in client.writes


def test_comando_idempotente_non_riscrive(db):
    now = datetime(2026, 3, 10, 3, 0)
    db.upsert_pianificazione(now, comando_strategico=ComandoStrategico.FORZATURA_RETE)
    client = FakeClient()
    loop = ControlLoop(_config(), client, db)

    loop.step(now)
    writes_after_first = len(client.writes)
    loop.step(now)

    assert len(client.writes) == writes_after_first


def test_ora_senza_piano_va_in_idle(db):
    now = datetime(2026, 3, 10, 12, 0)
    client = FakeClient()
    loop = ControlLoop(_config(), client, db)

    assert loop.step(now) is ComandoStrategico.IDLE


def test_dry_run_non_scrive_mai(db):
    now = datetime(2026, 3, 10, 19, 0)
    db.upsert_pianificazione(now, comando_strategico=ComandoStrategico.SCARICA_MASSIMA)
    client = FakeClient()
    loop = ControlLoop(_config(dry_run=True), client, db)

    loop.step(now)

    assert client.writes == []


def test_fallback_ripristina_autoconsumo(db):
    client = FakeClient()
    loop = ControlLoop(_config(), client, db)

    loop.fallback()

    assert client.fallback_called
