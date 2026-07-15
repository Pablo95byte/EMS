"""Fase 2 - Prezzi orari MGP (Mercato del Giorno Prima) dal GME.

Il GME pubblica ogni giorno alle ~13:00 i prezzi del giorno successivo in file
XML `YYYYMMDDMGPPrezzi.xml`. Il download automatico dal sito richiede
l'accettazione delle condizioni d'uso, quindi il modulo supporta due sorgenti:

1. file XML locale depositato in `gme.xml_dir` (anche via scp/rsync da altro job);
2. download HTTP dall'URL template configurato (se raggiungibile).

Formato XML: elementi <Prezzi> con figli <Ora> (1-24) e un tag per zona
(PUN, NORD, CSUD, ...) con il prezzo in EUR/MWh e la virgola come separatore
decimale.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from hems.config import GmeConfig
from hems.db.database import Database

log = logging.getLogger(__name__)


def parse_mgp_xml(xml_text: str, zone: str) -> dict[datetime, float]:
    """Ritorna {ora locale -> prezzo EUR/MWh} dal file MGPPrezzi.

    L'ora GME e' 1-based (Ora=1 -> 00:00-01:00). Nei giorni di cambio ora
    legale il file puo' avere 23 o 25 righe: le ore oltre la 24esima vengono
    ignorate (approssimazione accettabile per l'MVP).
    """
    root = ET.fromstring(xml_text)
    prices: dict[datetime, float] = {}
    for row in root.iter("Prezzi"):
        data_el = row.find("Data")
        ora_el = row.find("Ora")
        zone_el = row.find(zone)
        if data_el is None or ora_el is None or zone_el is None:
            continue
        if not (data_el.text and ora_el.text and zone_el.text):
            continue
        day = datetime.strptime(data_el.text.strip(), "%Y%m%d").date()
        hour = int(ora_el.text.strip()) - 1
        if not 0 <= hour <= 23:
            continue
        price = float(zone_el.text.strip().replace(",", "."))
        prices[datetime.combine(day, datetime.min.time()) + timedelta(hours=hour)] = (
            price
        )
    if not prices:
        raise ValueError(f"Nessun prezzo trovato per la zona '{zone}' nel file GME")
    return prices


def load_mgp_prices(config: GmeConfig, target_day: date) -> dict[datetime, float]:
    """Carica i prezzi per il giorno target: prima dal file locale, poi via HTTP."""
    filename = f"{target_day.strftime('%Y%m%d')}MGPPrezzi.xml"
    local_path = Path(config.xml_dir) / filename
    if local_path.exists():
        log.info("Prezzi GME da file locale %s", local_path)
        return parse_mgp_xml(local_path.read_text(encoding="utf-8"), config.zone)

    if config.download_url_template:
        url = config.download_url_template.format(date=target_day.strftime("%Y%m%d"))
        log.info("Download prezzi GME da %s", url)
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text(response.text, encoding="utf-8")
        return parse_mgp_xml(response.text, config.zone)

    raise FileNotFoundError(
        f"File prezzi GME non trovato ({local_path}) e nessun URL configurato"
    )


def store_mgp_prices(db: Database, config: GmeConfig, target_day: date) -> int:
    prices = load_mgp_prices(config, target_day)
    for hour, price in prices.items():
        db.upsert_pianificazione(hour, prezzo_energia_mwh=price)
    log.info(
        "Prezzi GME %s (%s): %d ore, min %.2f max %.2f EUR/MWh",
        target_day,
        config.zone,
        len(prices),
        min(prices.values()),
        max(prices.values()),
    )
    return len(prices)
