"""Client Modbus TCP per Huawei SUN2000.

Vincoli hardware rispettati qui:
- la Smart Dongle accetta una sola connessione Modbus attiva: il client e'
  un singolo oggetto con lock interno, da condividere tra collector e control loop;
- polling sotto i 10 secondi puo' far crashare la dongle: il client impone un
  intervallo minimo tra letture consecutive;
- la dongle impiega alcuni secondi dopo il connect prima di rispondere.
"""

from __future__ import annotations

import dataclasses
import logging
import threading
import time

from pymodbus.client import ModbusTcpClient

from hems.config import InverterConfig
from hems.modbus import registers as regs
from hems.modbus.registers import ForceCommand, Register, decode, encode

log = logging.getLogger(__name__)

# La dongle WLAN-FE non risponde subito dopo l'apertura della connessione TCP.
_POST_CONNECT_DELAY_S = 3.0


@dataclasses.dataclass(frozen=True)
class TelemetrySample:
    timestamp: float
    produzione_w: float
    meter_rete_w: float
    batteria_soc_perc: float
    batteria_w: float

    @property
    def consumo_casa_w(self) -> float:
        """Bilancio di casa: produzione - immissione in rete - carica batteria.

        meter_rete_w: + immette, - preleva. batteria_w: + carica, - scarica.
        """
        return self.produzione_w - self.meter_rete_w - self.batteria_w


class ModbusError(RuntimeError):
    pass


class HuaweiClient:
    """Accesso serializzato e rate-limited ai registri del SUN2000."""

    def __init__(self, config: InverterConfig):
        self._config = config
        self._lock = threading.Lock()
        self._client: ModbusTcpClient | None = None
        self._last_io_ts = 0.0

    # -- Connessione ---------------------------------------------------------

    def connect(self) -> None:
        with self._lock:
            self._connect_locked()

    def _connect_locked(self) -> None:
        if self._client is not None and self._client.connected:
            return
        client = ModbusTcpClient(
            host=self._config.host,
            port=self._config.port,
            timeout=self._config.connect_timeout_s,
        )
        if not client.connect():
            raise ModbusError(
                f"Connessione fallita a {self._config.host}:{self._config.port}"
            )
        time.sleep(_POST_CONNECT_DELAY_S)
        self._client = client
        log.info("Connesso a %s:%s", self._config.host, self._config.port)

    def close(self) -> None:
        with self._lock:
            if self._client is not None:
                self._client.close()
                self._client = None

    def _throttle_locked(self) -> None:
        elapsed = time.monotonic() - self._last_io_ts
        wait = self._config.min_poll_interval_s - elapsed
        if wait > 0:
            log.debug("Throttling dongle: attesa %.1fs", wait)
            time.sleep(wait)

    # -- Lettura ---------------------------------------------------------------

    def read_register(self, register: Register) -> float:
        with self._lock:
            self._connect_locked()
            self._throttle_locked()
            assert self._client is not None
            result = self._client.read_holding_registers(
                address=register.address,
                count=register.word_count,
                slave=self._config.slave_id,
            )
            self._last_io_ts = time.monotonic()
            if result.isError():
                raise ModbusError(f"Errore lettura registro {register.address}: {result}")
            return decode(register, list(result.registers))

    def read_telemetry(self) -> TelemetrySample:
        """Legge il set completo di telemetria (una transazione per registro)."""
        values: dict[str, float] = {}
        for register in regs.TELEMETRY_REGISTERS:
            values[register.name] = self.read_register(register)
        return TelemetrySample(
            timestamp=time.time(),
            produzione_w=values["produzione_w"],
            meter_rete_w=values["meter_rete_w"],
            batteria_soc_perc=values["batteria_soc_perc"],
            batteria_w=values["batteria_w"],
        )

    # -- Scrittura (controllo attivo) -----------------------------------------

    def write_register(self, register: Register, value: int) -> None:
        words = encode(register, value)
        with self._lock:
            self._connect_locked()
            self._throttle_locked()
            assert self._client is not None
            result = self._client.write_registers(
                address=register.address,
                values=words,
                slave=self._config.slave_id,
            )
            self._last_io_ts = time.monotonic()
            if result.isError():
                raise ModbusError(
                    f"Errore scrittura registro {register.address}: {result}"
                )
        log.info("Scritto registro %s = %s", register.address, value)

    def set_grid_charge(self, enabled: bool) -> None:
        self.write_register(regs.GRID_CHARGE_ENABLE, 1 if enabled else 0)

    def set_force_command(self, command: ForceCommand) -> None:
        self.write_register(regs.FORCE_COMMAND, int(command))

    def set_forced_charge_power(self, watts: int) -> None:
        self.write_register(regs.FORCED_CHARGE_POWER, watts)

    def set_max_grid_power(self, watts: int) -> None:
        self.write_register(regs.MAX_GRID_POWER, watts)

    def fallback_to_self_consumption(self) -> None:
        """Riporta l'inverter alla modalita' di default 'Massimo Autoconsumo'.

        Chiamata dalla logica di fall-back ogni volta che l'algoritmo va in errore:
        ferma le forzature e disabilita la carica da rete.
        """
        log.warning("FALLBACK: ripristino modalita' Massimo Autoconsumo")
        self.set_force_command(ForceCommand.STOP)
        self.set_grid_charge(False)
