"""Fase 3 - Motore di simulazione offline (backtesting).

Risponde alla domanda: "se il sistema avesse girato nel periodo X, quanti euro
avrebbe fatto risparmiare?". Confronta due strategie sugli stessi dati orari
(consumo, produzione, prezzi):

- BASELINE: massimo autoconsumo Huawei (la batteria assorbe il surplus solare
  e copre i deficit, senza guardare i prezzi);
- OTTIMIZZATA: il piano dell'ottimizzatore (carica notturna da rete nei giorni
  giusti, scarica concentrata nelle ore di picco).

Ipotesi semplificative dichiarate (MVP): passo orario, prezzo di acquisto =
prezzo MGP + oneri fissi, remunerazione immissione = prezzo MGP (RID).
"""

from __future__ import annotations

import dataclasses
import logging
from datetime import datetime

from hems.config import BatteryConfig, OptimizerConfig
from hems.db.database import ComandoStrategico
from hems.optimizer.planner import build_daily_plan
from hems.db.database import PianificazioneRow

log = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class HourData:
    """Dato orario aggregato per la simulazione."""
    hour: datetime
    consumo_kwh: float
    produzione_kwh: float
    prezzo_mwh: float


@dataclasses.dataclass
class SimResult:
    costo_eur: float = 0.0
    ricavo_eur: float = 0.0
    energia_acquistata_kwh: float = 0.0
    energia_immessa_kwh: float = 0.0

    @property
    def netto_eur(self) -> float:
        return self.costo_eur - self.ricavo_eur


@dataclasses.dataclass(frozen=True)
class BacktestReport:
    baseline: SimResult
    ottimizzata: SimResult

    @property
    def risparmio_eur(self) -> float:
        return self.baseline.netto_eur - self.ottimizzata.netto_eur


class _BatterySim:
    """Modello semplice di batteria a passo orario con efficienza round-trip."""

    def __init__(self, config: BatteryConfig, initial_soc_perc: float = 50.0):
        self._config = config
        self.energy_kwh = config.capacity_kwh * initial_soc_perc / 100.0
        # L'efficienza round-trip e' ripartita a meta' tra carica e scarica.
        self._eff_one_way = config.roundtrip_efficiency**0.5

    @property
    def soc_perc(self) -> float:
        return 100.0 * self.energy_kwh / self._config.capacity_kwh

    def charge(self, offered_kwh: float) -> float:
        """Carica fino ai limiti; ritorna l'energia effettivamente assorbita (lato AC)."""
        max_power_kwh = self._config.max_charge_w / 1000.0
        ceiling_kwh = self._config.capacity_kwh * self._config.soc_ceiling_perc / 100.0
        room_kwh = max(ceiling_kwh - self.energy_kwh, 0.0) / self._eff_one_way
        accepted = min(offered_kwh, max_power_kwh, room_kwh)
        self.energy_kwh += accepted * self._eff_one_way
        return accepted

    def discharge(self, requested_kwh: float) -> float:
        """Scarica fino ai limiti; ritorna l'energia erogata (lato AC)."""
        max_power_kwh = self._config.max_discharge_w / 1000.0
        floor_kwh = self._config.capacity_kwh * self._config.soc_floor_perc / 100.0
        available = max(self.energy_kwh - floor_kwh, 0.0) * self._eff_one_way
        delivered = min(requested_kwh, max_power_kwh, available)
        self.energy_kwh -= delivered / self._eff_one_way
        return delivered


def _settle_hour(
    result: SimResult, grid_import_kwh: float, grid_export_kwh: float, prezzo_mwh: float
) -> None:
    result.costo_eur += grid_import_kwh * prezzo_mwh / 1000.0
    result.ricavo_eur += grid_export_kwh * prezzo_mwh / 1000.0
    result.energia_acquistata_kwh += grid_import_kwh
    result.energia_immessa_kwh += grid_export_kwh


def _simulate(
    hours: list[HourData],
    battery: BatteryConfig,
    commands: dict[datetime, ComandoStrategico] | None,
    forced_charge_kwh: float,
) -> SimResult:
    """Simula il periodo. commands=None -> baseline massimo autoconsumo."""
    sim = _BatterySim(battery)
    result = SimResult()
    for hour in sorted(hours, key=lambda h: h.hour):
        comando = (
            commands.get(hour.hour, ComandoStrategico.IDLE)
            if commands is not None
            else ComandoStrategico.IDLE
        )
        surplus = hour.produzione_kwh - hour.consumo_kwh
        grid_import = 0.0
        grid_export = 0.0

        if comando is ComandoStrategico.FORZATURA_RETE:
            # Carica forzata da rete; il carico di casa resta sulla rete.
            charged = sim.charge(forced_charge_kwh)
            grid_import += charged
            if surplus >= 0:
                grid_export += surplus
            else:
                grid_import += -surplus
        elif comando is ComandoStrategico.SCARICA_MASSIMA:
            if surplus >= 0:
                grid_export += surplus
            else:
                delivered = sim.discharge(-surplus)
                grid_import += -surplus - delivered
        elif comando is ComandoStrategico.BLOCCO_SCARICA:
            if surplus >= 0:
                grid_export += surplus - sim.charge(surplus)
            else:
                grid_import += -surplus
        else:  # IDLE = massimo autoconsumo
            if surplus >= 0:
                grid_export += surplus - sim.charge(surplus)
            else:
                delivered = sim.discharge(-surplus)
                grid_import += -surplus - delivered

        _settle_hour(result, grid_import, grid_export, hour.prezzo_mwh)
    return result


def run_backtest(
    hours: list[HourData],
    battery: BatteryConfig,
    optimizer: OptimizerConfig,
) -> BacktestReport:
    """Esegue baseline vs strategia ottimizzata sugli stessi dati storici.

    Il piano ottimizzato e' ricalcolato giorno per giorno con le stesse regole
    del planner di produzione (stessi prezzi, produzione reale come 'forecast
    perfetto': il risparmio stimato e' quindi un upper bound).
    """
    by_day: dict[str, list[HourData]] = {}
    for hour in hours:
        by_day.setdefault(hour.hour.date().isoformat(), []).append(hour)

    commands: dict[datetime, ComandoStrategico] = {}
    for day_hours in by_day.values():
        rows = [
            PianificazioneRow(
                data_ora_target=h.hour,
                prezzo_energia_mwh=h.prezzo_mwh,
                produzione_solare_prevista_w=h.produzione_kwh * 1000.0,
                comando_strategico=ComandoStrategico.IDLE,
            )
            for h in day_hours
        ]
        for entry in build_daily_plan(rows, optimizer):
            commands[entry.hour] = entry.comando

    forced_charge_kwh = optimizer.forced_charge_w / 1000.0
    baseline = _simulate(hours, battery, None, forced_charge_kwh)
    ottimizzata = _simulate(hours, battery, commands, forced_charge_kwh)
    report = BacktestReport(baseline=baseline, ottimizzata=ottimizzata)
    log.info(
        "Backtest %d ore: baseline %.2f EUR, ottimizzata %.2f EUR, risparmio %.2f EUR",
        len(hours),
        baseline.netto_eur,
        ottimizzata.netto_eur,
        report.risparmio_eur,
    )
    return report
