from datetime import datetime, timedelta

from hems.config import BatteryConfig, OptimizerConfig
from hems.simulation.backtest import HourData, run_backtest

BATTERY = BatteryConfig(
    capacity_kwh=10.0,
    max_charge_w=5000,
    max_discharge_w=5000,
    soc_floor_perc=15.0,
    roundtrip_efficiency=0.90,
)
OPT = OptimizerConfig(
    night_hours=(2, 3, 4),
    peak_hours=(19, 20, 21),
    night_price_ratio=0.40,
    low_solar_day_kwh=8.0,
    forced_charge_w=3000,
)


def _rainy_day() -> list[HourData]:
    """Giorno di pioggia: zero solare, notte a 50 EUR/MWh, sera a 250."""
    base = datetime(2026, 3, 10)
    hours = []
    for h in range(24):
        if h in (2, 3, 4):
            price = 50.0
        elif h in (19, 20, 21):
            price = 250.0
        else:
            price = 120.0
        hours.append(
            HourData(
                hour=base + timedelta(hours=h),
                consumo_kwh=1.0,
                produzione_kwh=0.0,
                prezzo_mwh=price,
            )
        )
    return hours


def test_arbitraggio_fa_risparmiare_in_giorno_di_pioggia():
    report = run_backtest(_rainy_day(), BATTERY, OPT)
    # Con zero solare la baseline compra tutto a prezzo pieno; la strategia
    # ottimizzata sposta acquisti dalle ore a 250 alle ore a 50.
    assert report.risparmio_eur > 0


def test_bilanci_energetici_coerenti():
    report = run_backtest(_rainy_day(), BATTERY, OPT)
    consumo_tot = 24.0  # 1 kWh/ora
    # La baseline senza solare deve comprare almeno il consumo totale
    # (la batteria parte a 50% quindi puo' coprire una parte).
    assert report.baseline.energia_acquistata_kwh >= consumo_tot - 5.0 * 0.95
    # L'ottimizzata compra di piu' (carica anche la batteria) ma spende meno.
    assert (
        report.ottimizzata.energia_acquistata_kwh
        >= report.baseline.energia_acquistata_kwh
    )
    assert report.ottimizzata.netto_eur < report.baseline.netto_eur


def test_soc_floor_rispettato():
    # Giorno con consumo alto e batteria piccola: la scarica non deve mai
    # portare la batteria sotto il floor (verificato indirettamente: l'energia
    # scaricabile e' limitata e il resto viene comprato).
    battery = BatteryConfig(
        capacity_kwh=2.0,
        max_charge_w=5000,
        max_discharge_w=5000,
        soc_floor_perc=15.0,
        roundtrip_efficiency=1.0,
    )
    report = run_backtest(_rainy_day(), battery, OPT)
    # Capacita' utile = 2 kWh * 85%: l'acquisto baseline deve coprire quasi tutto.
    assert report.baseline.energia_acquistata_kwh >= 24.0 - 2.0 * 0.85 - 1e-6
