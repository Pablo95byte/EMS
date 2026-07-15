"""Fase 4 - Control loop "write-mode": dal piano su DB ai comandi Modbus.

Principi di sicurezza:
- protezione SoC a runtime: mai forzare la scarica sotto `soc_floor_perc`,
  qualunque cosa dica il piano;
- comandi idempotenti: si scrive sull'inverter solo quando il comando cambia,
  per minimizzare il traffico verso la dongle;
- fall-back to normal: qualsiasi errore non gestito riporta l'inverter alla
  modalita' di default Huawei "Massimo Autoconsumo" prima di uscire;
- dry-run: con control.dry_run=true i comandi vengono solo loggati su DB.
  E' la modalita' con cui iniziare i test della Fase 4.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from hems.config import Config
from hems.db.database import ComandoStrategico, Database
from hems.modbus import registers as regs
from hems.modbus.client import HuaweiClient, ModbusError
from hems.modbus.registers import ForceCommand

log = logging.getLogger(__name__)


class ControlLoop:
    def __init__(self, config: Config, client: HuaweiClient, db: Database):
        self._config = config
        self._client = client
        self._db = db
        self._active_command: ComandoStrategico | None = None

    # -- Applicazione comandi ---------------------------------------------------

    def _write(self, register: regs.Register, value: int, comando: str) -> None:
        dry_run = self._config.control.dry_run
        esito = "DRY_RUN"
        if not dry_run:
            try:
                self._client.write_register(register, value)
                esito = "OK"
            except Exception as exc:
                esito = f"ERRORE: {exc}"
                raise
            finally:
                self._db.log_comando(
                    datetime.now(timezone.utc), register.address, value, comando,
                    esito, dry_run,
                )
        else:
            log.info("[DRY-RUN] registro %s = %s (%s)", register.address, value, comando)
            self._db.log_comando(
                datetime.now(timezone.utc), register.address, value, comando,
                esito, dry_run,
            )

    def _apply(self, comando: ComandoStrategico) -> None:
        if comando == self._active_command:
            return
        log.info("Cambio comando: %s -> %s", self._active_command, comando)
        opt = self._config.optimizer
        name = comando.value
        if comando is ComandoStrategico.FORZATURA_RETE:
            self._write(regs.MAX_GRID_POWER, opt.max_grid_power_w, name)
            self._write(regs.FORCED_CHARGE_POWER, opt.forced_charge_w, name)
            self._write(regs.GRID_CHARGE_ENABLE, 1, name)
            self._write(regs.FORCE_COMMAND, int(ForceCommand.FORCE_CHARGE), name)
        elif comando is ComandoStrategico.SCARICA_MASSIMA:
            self._write(regs.GRID_CHARGE_ENABLE, 0, name)
            self._write(regs.FORCE_COMMAND, int(ForceCommand.FORCE_DISCHARGE), name)
        else:  # IDLE / BLOCCO_SCARICA -> default Huawei
            self._write(regs.FORCE_COMMAND, int(ForceCommand.STOP), name)
            self._write(regs.GRID_CHARGE_ENABLE, 0, name)
        self._active_command = comando

    def fallback(self) -> None:
        """Riporta l'inverter al default Huawei. Non deve mai sollevare."""
        try:
            if self._config.control.dry_run:
                log.warning("[DRY-RUN] fallback a Massimo Autoconsumo")
            else:
                self._client.fallback_to_self_consumption()
            self._db.log_comando(
                datetime.now(timezone.utc), regs.FORCE_COMMAND.address, 0,
                "FALLBACK_AUTOCONSUMO", "OK", self._config.control.dry_run,
            )
        except Exception:
            log.exception(
                "FALLBACK FALLITO: verificare manualmente lo stato dell'inverter!"
            )
        finally:
            self._active_command = None

    # -- Ciclo -------------------------------------------------------------------

    def step(self, now: datetime | None = None) -> ComandoStrategico:
        """Un giro di controllo: legge piano + telemetria e applica il comando."""
        now = now or datetime.now()
        row = self._db.pianificazione_for_hour(now)
        comando = row.comando_strategico if row else ComandoStrategico.IDLE
        if row is None:
            log.warning("Nessun piano per le %s: resto in IDLE", now.strftime("%H:00"))

        # Protezione SoC: la scarica forzata e' vietata sotto la soglia.
        if comando is ComandoStrategico.SCARICA_MASSIMA:
            soc = self._client.read_register(regs.BATTERY_SOC)
            if soc <= self._config.battery.soc_floor_perc:
                log.warning(
                    "SoC %.1f%% <= soglia %.1f%%: SCARICA_MASSIMA -> IDLE",
                    soc,
                    self._config.battery.soc_floor_perc,
                )
                comando = ComandoStrategico.IDLE

        self._apply(comando)
        return comando

    def run(self) -> None:
        interval = self._config.control.loop_interval_s
        log.info(
            "Control loop avviato (intervallo %.0fs, dry_run=%s)",
            interval,
            self._config.control.dry_run,
        )
        try:
            while True:
                started = time.monotonic()
                try:
                    self.step()
                except ModbusError as exc:
                    # Errore di comunicazione: fallback e riprova al giro dopo.
                    log.error("Errore Modbus nel control loop: %s", exc)
                    self._client.close()
                    self.fallback()
                elapsed = time.monotonic() - started
                time.sleep(max(interval - elapsed, 1.0))
        except BaseException:
            # Uscita per qualsiasi motivo (bug, Ctrl-C, SIGTERM):
            # mai lasciare l'inverter in uno stato forzato.
            log.exception("Control loop interrotto: eseguo fallback")
            self.fallback()
            raise
