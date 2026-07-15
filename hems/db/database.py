"""Persistenza timeseries su SQLite (schema portabile a PostgreSQL).

Tabelle:
- telemetria_reale: campioni dal campo (Fase 1);
- pianificazione_oraria: piano giornaliero prezzi/forecast/comandi (Fasi 2-3);
- log_comandi: audit trail dei comandi inviati all'inverter (Fase 4).
"""

from __future__ import annotations

import dataclasses
import sqlite3
from datetime import datetime
from enum import StrEnum
from pathlib import Path


class ComandoStrategico(StrEnum):
    IDLE = "IDLE"                          # Massimo autoconsumo (default Huawei)
    FORZATURA_RETE = "FORZATURA_RETE"      # Carica forzata da rete (arbitraggio)
    SCARICA_MASSIMA = "SCARICA_MASSIMA"    # Scarica forzata (peak shaving serale)
    BLOCCO_SCARICA = "BLOCCO_SCARICA"      # Conserva SoC (protezione batteria)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS telemetria_reale (
    timestamp           TEXT PRIMARY KEY,   -- ISO 8601 UTC
    produzione_w        REAL NOT NULL,
    consumo_casa_w      REAL NOT NULL,
    meter_rete_w        REAL NOT NULL,
    batteria_w          REAL NOT NULL,
    batteria_soc_perc   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS pianificazione_oraria (
    data_ora_target             TEXT PRIMARY KEY,   -- ISO 8601, ora locale troncata
    prezzo_energia_mwh          REAL,
    produzione_solare_prevista_w REAL,
    comando_strategico          TEXT NOT NULL DEFAULT 'IDLE'
);

CREATE TABLE IF NOT EXISTS log_comandi (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    registro    INTEGER NOT NULL,
    valore      INTEGER NOT NULL,
    comando     TEXT NOT NULL,
    esito       TEXT NOT NULL,
    dry_run     INTEGER NOT NULL DEFAULT 0
);
"""


@dataclasses.dataclass(frozen=True)
class PianificazioneRow:
    data_ora_target: datetime
    prezzo_energia_mwh: float | None
    produzione_solare_prevista_w: float | None
    comando_strategico: ComandoStrategico


class Database:
    def __init__(self, path: str | Path):
        db_path = Path(path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # -- Telemetria ------------------------------------------------------------

    def insert_telemetria(
        self,
        timestamp: datetime,
        produzione_w: float,
        consumo_casa_w: float,
        meter_rete_w: float,
        batteria_w: float,
        batteria_soc_perc: float,
    ) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO telemetria_reale VALUES (?, ?, ?, ?, ?, ?)",
            (
                timestamp.isoformat(),
                produzione_w,
                consumo_casa_w,
                meter_rete_w,
                batteria_w,
                batteria_soc_perc,
            ),
        )
        self._conn.commit()

    def telemetria_between(
        self, start: datetime, end: datetime
    ) -> list[sqlite3.Row]:
        self._conn.row_factory = sqlite3.Row
        cur = self._conn.execute(
            "SELECT * FROM telemetria_reale WHERE timestamp >= ? AND timestamp < ?"
            " ORDER BY timestamp",
            (start.isoformat(), end.isoformat()),
        )
        return cur.fetchall()

    # -- Pianificazione ----------------------------------------------------------

    def upsert_pianificazione(
        self,
        data_ora_target: datetime,
        prezzo_energia_mwh: float | None = None,
        produzione_solare_prevista_w: float | None = None,
        comando_strategico: ComandoStrategico | None = None,
    ) -> None:
        """Aggiorna solo i campi forniti, preservando gli altri (i job prezzi,
        meteo e ottimizzatore scrivono in momenti diversi sulla stessa riga)."""
        key = data_ora_target.replace(minute=0, second=0, microsecond=0).isoformat()
        self._conn.execute(
            "INSERT INTO pianificazione_oraria (data_ora_target) VALUES (?)"
            " ON CONFLICT(data_ora_target) DO NOTHING",
            (key,),
        )
        sets, params = [], []
        if prezzo_energia_mwh is not None:
            sets.append("prezzo_energia_mwh = ?")
            params.append(prezzo_energia_mwh)
        if produzione_solare_prevista_w is not None:
            sets.append("produzione_solare_prevista_w = ?")
            params.append(produzione_solare_prevista_w)
        if comando_strategico is not None:
            sets.append("comando_strategico = ?")
            params.append(comando_strategico.value)
        if sets:
            params.append(key)
            self._conn.execute(
                f"UPDATE pianificazione_oraria SET {', '.join(sets)}"
                " WHERE data_ora_target = ?",
                params,
            )
        self._conn.commit()

    def pianificazione_for_hour(self, when: datetime) -> PianificazioneRow | None:
        key = when.replace(minute=0, second=0, microsecond=0).isoformat()
        cur = self._conn.execute(
            "SELECT data_ora_target, prezzo_energia_mwh,"
            " produzione_solare_prevista_w, comando_strategico"
            " FROM pianificazione_oraria WHERE data_ora_target = ?",
            (key,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return PianificazioneRow(
            data_ora_target=datetime.fromisoformat(row[0]),
            prezzo_energia_mwh=row[1],
            produzione_solare_prevista_w=row[2],
            comando_strategico=ComandoStrategico(row[3]),
        )

    def pianificazione_between(
        self, start: datetime, end: datetime
    ) -> list[PianificazioneRow]:
        cur = self._conn.execute(
            "SELECT data_ora_target, prezzo_energia_mwh,"
            " produzione_solare_prevista_w, comando_strategico"
            " FROM pianificazione_oraria"
            " WHERE data_ora_target >= ? AND data_ora_target < ?"
            " ORDER BY data_ora_target",
            (start.isoformat(), end.isoformat()),
        )
        return [
            PianificazioneRow(
                data_ora_target=datetime.fromisoformat(r[0]),
                prezzo_energia_mwh=r[1],
                produzione_solare_prevista_w=r[2],
                comando_strategico=ComandoStrategico(r[3]),
            )
            for r in cur.fetchall()
        ]

    # -- Log comandi -------------------------------------------------------------

    def log_comando(
        self,
        timestamp: datetime,
        registro: int,
        valore: int,
        comando: str,
        esito: str,
        dry_run: bool,
    ) -> None:
        self._conn.execute(
            "INSERT INTO log_comandi (timestamp, registro, valore, comando, esito,"
            " dry_run) VALUES (?, ?, ?, ?, ?, ?)",
            (timestamp.isoformat(), registro, valore, comando, esito, int(dry_run)),
        )
        self._conn.commit()
