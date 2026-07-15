"""Ottimizzatore giornaliero: dalla tabella prezzi/forecast al piano di comandi.

Regole implementate (in ordine di priorita' crescente sull'ora):

1. Arbitraggio notturno: se il prezzo medio nelle ore notturne e' sotto la
   soglia `night_price_ratio` rispetto al picco serale E la produzione solare
   prevista del giorno e' scarsa, le ore notturne diventano FORZATURA_RETE.
2. Scarica serale: nelle ore di picco prezzi, se la batteria e' stata caricata
   (o il giorno e' scarso), l'ora diventa SCARICA_MASSIMA.
3. Tutte le altre ore restano IDLE (massimo autoconsumo Huawei).

La protezione SoC (mai sotto soc_floor_perc) e' applicata a runtime dal
control loop, non qui: il piano e' calcolato il giorno prima quando lo stato
reale della batteria non e' ancora noto.
"""

from __future__ import annotations

import dataclasses
import logging
from datetime import date, datetime, timedelta

from hems.config import OptimizerConfig
from hems.db.database import ComandoStrategico, Database, PianificazioneRow

log = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class HourlyPlan:
    hour: datetime
    prezzo_energia_mwh: float | None
    produzione_solare_prevista_w: float | None
    comando: ComandoStrategico


def build_daily_plan(
    rows: list[PianificazioneRow], config: OptimizerConfig
) -> list[HourlyPlan]:
    """Applica le regole economiche alle 24 righe orarie di un giorno."""
    by_hour = {row.data_ora_target.hour: row for row in rows}

    night_prices = [
        by_hour[h].prezzo_energia_mwh
        for h in config.night_hours
        if h in by_hour and by_hour[h].prezzo_energia_mwh is not None
    ]
    peak_prices = [
        by_hour[h].prezzo_energia_mwh
        for h in config.peak_hours
        if h in by_hour and by_hour[h].prezzo_energia_mwh is not None
    ]
    solar_wh = sum(
        row.produzione_solare_prevista_w or 0.0 for row in rows
    )  # 1 campione/ora -> Wh
    solar_kwh = solar_wh / 1000.0

    arbitrage = False
    if night_prices and peak_prices:
        avg_night = sum(night_prices) / len(night_prices)
        peak = max(peak_prices)
        price_ok = avg_night < config.night_price_ratio * peak
        solar_low = solar_kwh < config.low_solar_day_kwh
        arbitrage = price_ok and solar_low
        log.info(
            "Arbitraggio notturno: prezzo notte %.2f vs picco %.2f (soglia %.0f%%),"
            " solare previsto %.1f kWh (soglia %.1f) -> %s",
            avg_night,
            peak,
            config.night_price_ratio * 100,
            solar_kwh,
            config.low_solar_day_kwh,
            "ATTIVO" if arbitrage else "no",
        )

    plan: list[HourlyPlan] = []
    for row in sorted(rows, key=lambda r: r.data_ora_target):
        hour = row.data_ora_target.hour
        if arbitrage and hour in config.night_hours:
            comando = ComandoStrategico.FORZATURA_RETE
        elif hour in config.peak_hours and (arbitrage or peak_prices):
            # Nelle ore di picco scarichiamo sempre: se non c'e' stata carica
            # notturna la batteria contiene comunque il surplus solare del giorno.
            comando = ComandoStrategico.SCARICA_MASSIMA
        else:
            comando = ComandoStrategico.IDLE
        plan.append(
            HourlyPlan(
                hour=row.data_ora_target,
                prezzo_energia_mwh=row.prezzo_energia_mwh,
                produzione_solare_prevista_w=row.produzione_solare_prevista_w,
                comando=comando,
            )
        )
    return plan


def plan_day(db: Database, config: OptimizerConfig, target_day: date) -> list[HourlyPlan]:
    """Calcola e persiste il piano per il giorno target."""
    start = datetime.combine(target_day, datetime.min.time())
    rows = db.pianificazione_between(start, start + timedelta(days=1))
    if not rows:
        raise ValueError(
            f"Nessun dato di pianificazione per {target_day}:"
            " eseguire prima i job prezzi e forecast"
        )
    plan = build_daily_plan(rows, config)
    for entry in plan:
        db.upsert_pianificazione(entry.hour, comando_strategico=entry.comando)
    actions = sum(1 for p in plan if p.comando is not ComandoStrategico.IDLE)
    log.info("Piano %s salvato: %d ore attive su %d", target_day, actions, len(plan))
    return plan
