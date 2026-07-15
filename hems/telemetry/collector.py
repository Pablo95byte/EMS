"""Fase 1 - Acquisizione dati: polling della telemetria e salvataggio su DB.

Da validare confrontando i valori con l'app FusionSolar.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from hems.config import Config
from hems.db.database import Database
from hems.modbus.client import HuaweiClient, ModbusError

log = logging.getLogger(__name__)


def collect_once(client: HuaweiClient, db: Database) -> None:
    sample = client.read_telemetry()
    db.insert_telemetria(
        timestamp=datetime.fromtimestamp(sample.timestamp, tz=timezone.utc),
        produzione_w=sample.produzione_w,
        consumo_casa_w=sample.consumo_casa_w,
        meter_rete_w=sample.meter_rete_w,
        batteria_w=sample.batteria_w,
        batteria_soc_perc=sample.batteria_soc_perc,
    )
    log.info(
        "PV=%.0fW casa=%.0fW rete=%.0fW batt=%.0fW SoC=%.1f%%",
        sample.produzione_w,
        sample.consumo_casa_w,
        sample.meter_rete_w,
        sample.batteria_w,
        sample.batteria_soc_perc,
    )


def run_collector(config: Config, client: HuaweiClient, db: Database) -> None:
    """Loop infinito di acquisizione. Gli errori Modbus non fermano il loop:
    la dongle a volte non risponde e si riprende al giro successivo."""
    interval = config.telemetry_poll_interval_s
    log.info("Collector avviato, intervallo %.0fs", interval)
    while True:
        started = time.monotonic()
        try:
            collect_once(client, db)
        except ModbusError as exc:
            log.warning("Lettura fallita, riprovo al prossimo giro: %s", exc)
            client.close()
        except Exception:
            log.exception("Errore inatteso nel collector")
            client.close()
        elapsed = time.monotonic() - started
        time.sleep(max(interval - elapsed, 1.0))
