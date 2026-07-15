"""Entry point CLI del sistema HEMS.

Comandi:
  hems collect                        Fase 1: loop di acquisizione telemetria
  hems fetch-forecast [--date ...]    Fase 2: forecast solare Open-Meteo
  hems fetch-prices  [--date ...]     Fase 2: prezzi MGP dal GME
  hems plan          [--date ...]     Fase 3: calcolo del piano giornaliero
  hems backtest --start ... --end ... Fase 3: backtesting su dati storici
  hems control                        Fase 4: control loop write-mode
  hems test-force [--minutes 5]       Fase 4: test isolato di scarica forzata
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, datetime, timedelta, timezone

from hems.config import Config, load_config

log = logging.getLogger(__name__)


def _tomorrow() -> date:
    return date.today() + timedelta(days=1)


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def cmd_collect(config: Config, _: argparse.Namespace) -> int:
    from hems.db.database import Database
    from hems.modbus.client import HuaweiClient
    from hems.telemetry.collector import run_collector

    client = HuaweiClient(config.inverter)
    db = Database(config.db_path)
    try:
        run_collector(config, client, db)
    except KeyboardInterrupt:
        log.info("Collector fermato")
    finally:
        client.close()
        db.close()
    return 0


def cmd_fetch_forecast(config: Config, args: argparse.Namespace) -> int:
    from hems.datalake.openmeteo import store_solar_forecast
    from hems.db.database import Database

    db = Database(config.db_path)
    try:
        hours = store_solar_forecast(db, config.plant, args.date)
        print(f"Forecast solare salvato: {hours} ore per {args.date}")
    finally:
        db.close()
    return 0


def cmd_fetch_prices(config: Config, args: argparse.Namespace) -> int:
    from hems.datalake.gme import store_mgp_prices
    from hems.db.database import Database

    db = Database(config.db_path)
    try:
        hours = store_mgp_prices(db, config.gme, args.date)
        print(f"Prezzi MGP salvati: {hours} ore per {args.date}")
    finally:
        db.close()
    return 0


def cmd_plan(config: Config, args: argparse.Namespace) -> int:
    from hems.db.database import Database
    from hems.optimizer.planner import plan_day

    db = Database(config.db_path)
    try:
        plan = plan_day(db, config.optimizer, args.date)
        for entry in plan:
            prezzo = (
                f"{entry.prezzo_energia_mwh:7.2f}"
                if entry.prezzo_energia_mwh is not None
                else "    n/d"
            )
            solare = (
                f"{entry.produzione_solare_prevista_w:6.0f}"
                if entry.produzione_solare_prevista_w is not None
                else "   n/d"
            )
            print(
                f"{entry.hour:%Y-%m-%d %H:00}  {prezzo} EUR/MWh"
                f"  PV {solare} W  {entry.comando.value}"
            )
    finally:
        db.close()
    return 0


def cmd_backtest(config: Config, args: argparse.Namespace) -> int:
    from hems.db.database import Database
    from hems.simulation.backtest import HourData, run_backtest

    db = Database(config.db_path)
    try:
        start = datetime.combine(args.start, datetime.min.time(), tzinfo=timezone.utc)
        end = datetime.combine(args.end, datetime.min.time(), tzinfo=timezone.utc)
        telemetria = db.telemetria_between(start, end)
        if not telemetria:
            print(
                f"Nessuna telemetria tra {args.start} e {args.end}:"
                " eseguire prima 'hems collect'",
                file=sys.stderr,
            )
            return 1

        # Aggrega la telemetria (campioni al minuto) in ore ed energia (kWh).
        buckets: dict[str, dict[str, list[float]]] = {}
        for row in telemetria:
            ts = datetime.fromisoformat(row["timestamp"])
            key = ts.replace(minute=0, second=0, microsecond=0).isoformat()
            bucket = buckets.setdefault(key, {"consumo": [], "produzione": []})
            bucket["consumo"].append(row["consumo_casa_w"])
            bucket["produzione"].append(row["produzione_w"])

        prezzi = {
            r.data_ora_target.replace(tzinfo=timezone.utc).isoformat():
                r.prezzo_energia_mwh
            for r in db.pianificazione_between(
                start.replace(tzinfo=None), end.replace(tzinfo=None)
            )
            if r.prezzo_energia_mwh is not None
        }

        hours: list[HourData] = []
        for key, bucket in buckets.items():
            prezzo = prezzi.get(key)
            if prezzo is None:
                continue
            avg = lambda values: sum(values) / len(values)
            hours.append(
                HourData(
                    hour=datetime.fromisoformat(key),
                    consumo_kwh=avg(bucket["consumo"]) / 1000.0,
                    produzione_kwh=avg(bucket["produzione"]) / 1000.0,
                    prezzo_mwh=prezzo,
                )
            )
        if not hours:
            print(
                "Telemetria presente ma nessun prezzo MGP corrispondente:"
                " eseguire 'hems fetch-prices' per il periodo",
                file=sys.stderr,
            )
            return 1

        report = run_backtest(hours, config.battery, config.optimizer)
        print(f"Ore simulate:          {len(hours)}")
        print(f"Costo baseline:        {report.baseline.netto_eur:8.2f} EUR")
        print(f"Costo ottimizzato:     {report.ottimizzata.netto_eur:8.2f} EUR")
        print(f"Risparmio stimato:     {report.risparmio_eur:8.2f} EUR")
    finally:
        db.close()
    return 0


def cmd_control(config: Config, _: argparse.Namespace) -> int:
    from hems.control.control_loop import ControlLoop
    from hems.db.database import Database
    from hems.modbus.client import HuaweiClient

    client = HuaweiClient(config.inverter)
    db = Database(config.db_path)
    loop = ControlLoop(config, client, db)
    try:
        loop.run()
    except KeyboardInterrupt:
        log.info("Control loop fermato dall'utente")
    finally:
        client.close()
        db.close()
    return 0


def cmd_test_force(config: Config, args: argparse.Namespace) -> int:
    """Test isolato Fase 4: forza la scarica per N minuti e osserva la risposta."""
    from hems.modbus import registers as regs
    from hems.modbus.client import HuaweiClient
    from hems.modbus.registers import ForceCommand

    client = HuaweiClient(config.inverter)
    try:
        soc = client.read_register(regs.BATTERY_SOC)
        if soc <= config.battery.soc_floor_perc:
            print(f"SoC {soc:.1f}% sotto la soglia: test annullato", file=sys.stderr)
            return 1
        print(f"SoC iniziale {soc:.1f}% - forzo la scarica per {args.minutes} min")
        if config.control.dry_run:
            print("dry_run=true in configurazione: nessuna scrittura eseguita")
            return 0
        client.set_force_command(ForceCommand.FORCE_DISCHARGE)
        deadline = time.monotonic() + args.minutes * 60
        while time.monotonic() < deadline:
            time.sleep(max(config.inverter.min_poll_interval_s, 15))
            batt_w = client.read_register(regs.BATTERY_POWER)
            soc = client.read_register(regs.BATTERY_SOC)
            print(f"  batteria {batt_w:+.0f} W, SoC {soc:.1f}%")
            if soc <= config.battery.soc_floor_perc:
                print("Soglia SoC raggiunta: interrompo il test")
                break
    finally:
        # Qualunque cosa succeda, ripristina il default Huawei.
        try:
            if not config.control.dry_run:
                client.fallback_to_self_consumption()
                print("Inverter riportato a Massimo Autoconsumo")
        finally:
            client.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hems", description="HEMS Predittivo")
    parser.add_argument("--config", help="percorso file di configurazione YAML")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("collect", help="Fase 1: loop telemetria")

    p = sub.add_parser("fetch-forecast", help="Fase 2: forecast solare Open-Meteo")
    p.add_argument("--date", type=_parse_date, default=_tomorrow())

    p = sub.add_parser("fetch-prices", help="Fase 2: prezzi MGP GME")
    p.add_argument("--date", type=_parse_date, default=_tomorrow())

    p = sub.add_parser("plan", help="Fase 3: calcolo piano giornaliero")
    p.add_argument("--date", type=_parse_date, default=_tomorrow())

    p = sub.add_parser("backtest", help="Fase 3: backtesting su dati storici")
    p.add_argument("--start", type=_parse_date, required=True)
    p.add_argument("--end", type=_parse_date, required=True)

    sub.add_parser("control", help="Fase 4: control loop write-mode")

    p = sub.add_parser("test-force", help="Fase 4: test isolato scarica forzata")
    p.add_argument("--minutes", type=int, default=5)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config(args.config)

    handlers = {
        "collect": cmd_collect,
        "fetch-forecast": cmd_fetch_forecast,
        "fetch-prices": cmd_fetch_prices,
        "plan": cmd_plan,
        "backtest": cmd_backtest,
        "control": cmd_control,
        "test-force": cmd_test_force,
    }
    return handlers[args.command](config, args)


if __name__ == "__main__":
    sys.exit(main())
