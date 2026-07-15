from datetime import datetime, timedelta

from hems.config import OptimizerConfig
from hems.db.database import ComandoStrategico, PianificazioneRow
from hems.optimizer.planner import build_daily_plan

OPT = OptimizerConfig(
    night_hours=(2, 3, 4),
    peak_hours=(19, 20, 21),
    night_price_ratio=0.40,
    low_solar_day_kwh=8.0,
)


def _day(prices: dict[int, float], solar_w: dict[int, float]) -> list[PianificazioneRow]:
    base = datetime(2026, 3, 10)
    return [
        PianificazioneRow(
            data_ora_target=base + timedelta(hours=h),
            prezzo_energia_mwh=prices.get(h, 100.0),
            produzione_solare_prevista_w=solar_w.get(h, 0.0),
            comando_strategico=ComandoStrategico.IDLE,
        )
        for h in range(24)
    ]


def test_arbitraggio_notturno_attivo_con_prezzi_bassi_e_solare_scarso():
    # Notte a 50, picco serale a 200 (50 < 40% * 200 = 80), giorno di pioggia.
    prices = {2: 50.0, 3: 50.0, 4: 50.0, 19: 200.0, 20: 190.0, 21: 180.0}
    plan = build_daily_plan(_day(prices, {}), OPT)
    by_hour = {p.hour.hour: p.comando for p in plan}
    assert by_hour[2] is ComandoStrategico.FORZATURA_RETE
    assert by_hour[3] is ComandoStrategico.FORZATURA_RETE
    assert by_hour[19] is ComandoStrategico.SCARICA_MASSIMA
    assert by_hour[12] is ComandoStrategico.IDLE


def test_arbitraggio_disattivo_se_giornata_soleggiata():
    prices = {2: 50.0, 3: 50.0, 4: 50.0, 19: 200.0, 20: 190.0, 21: 180.0}
    # 3 kW costanti dalle 9 alle 16 -> ~24 kWh, ben oltre la soglia di 8.
    solar = {h: 3000.0 for h in range(9, 17)}
    plan = build_daily_plan(_day(prices, solar), OPT)
    by_hour = {p.hour.hour: p.comando for p in plan}
    assert by_hour[2] is ComandoStrategico.IDLE
    # La scarica serale resta attiva: la batteria contiene il surplus solare.
    assert by_hour[19] is ComandoStrategico.SCARICA_MASSIMA


def test_arbitraggio_disattivo_se_prezzo_notturno_alto():
    # Notte a 100 >= 40% * 200 = 80 -> niente carica notturna.
    prices = {2: 100.0, 3: 100.0, 4: 100.0, 19: 200.0, 20: 190.0, 21: 180.0}
    plan = build_daily_plan(_day(prices, {}), OPT)
    by_hour = {p.hour.hour: p.comando for p in plan}
    assert by_hour[2] is ComandoStrategico.IDLE
