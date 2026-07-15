"""Mappa dei registri Modbus TCP dell'inverter Huawei SUN2000 (via Smart Dongle).

Tipi dati Huawei: i registri a 32 bit occupano 2 word consecutive, big-endian
(word alta prima). I valori con "gain" vanno divisi per il fattore indicato.
"""

from __future__ import annotations

import dataclasses
import enum


class RegType(enum.Enum):
    UINT16 = "uint16"
    INT32 = "int32"
    UINT32 = "uint32"


@dataclasses.dataclass(frozen=True)
class Register:
    address: int
    reg_type: RegType
    name: str
    unit: str = ""
    gain: float = 1.0
    writable: bool = False

    @property
    def word_count(self) -> int:
        return 1 if self.reg_type is RegType.UINT16 else 2


# --- Telemetria (Read-Only) -------------------------------------------------

# Potenza attiva AC prodotta dall'inverter.
INVERTER_ACTIVE_POWER = Register(32080, RegType.INT32, "produzione_w", "W")
# Potenza allo Smart Meter DTSU666-H: + immissione in rete, - prelievo.
METER_ACTIVE_POWER = Register(37113, RegType.INT32, "meter_rete_w", "W")
# Stato di carica batteria LUNA2000, passo 0.1% (500 -> 50.0%).
BATTERY_SOC = Register(37004, RegType.UINT16, "batteria_soc_perc", "%", gain=10.0)
# Potenza batteria: + in carica, - in scarica.
BATTERY_POWER = Register(37001, RegType.INT32, "batteria_w", "W")

TELEMETRY_REGISTERS = (
    INVERTER_ACTIVE_POWER,
    METER_ACTIVE_POWER,
    BATTERY_SOC,
    BATTERY_POWER,
)

# --- Controllo attivo (Write) -----------------------------------------------

# Abilitazione carica da rete (AC charging): 1 = abilitato, 0 = disabilitato.
GRID_CHARGE_ENABLE = Register(
    47087, RegType.UINT16, "grid_charge_enable", writable=True
)
# Comando di forzatura: 0 = stop, 1 = forza carica, 2 = forza scarica.
FORCE_COMMAND = Register(47100, RegType.UINT16, "force_command", writable=True)
# Potenza massima di carica forzata.
FORCED_CHARGE_POWER = Register(
    47247, RegType.UINT32, "forced_charge_power_w", "W", writable=True
)
# Potenza massima prelevabile dalla rete.
MAX_GRID_POWER = Register(
    47242, RegType.UINT32, "max_grid_power_w", "W", writable=True
)


class ForceCommand(enum.IntEnum):
    STOP = 0
    FORCE_CHARGE = 1
    FORCE_DISCHARGE = 2


def decode(register: Register, words: list[int]) -> float:
    """Decodifica le word Modbus grezze nel valore fisico (applicando il gain)."""
    if len(words) != register.word_count:
        raise ValueError(
            f"Registro {register.address}: attese {register.word_count} word, "
            f"ricevute {len(words)}"
        )
    if register.reg_type is RegType.UINT16:
        raw = words[0]
    else:
        raw = (words[0] << 16) | words[1]
        if register.reg_type is RegType.INT32 and raw >= 2**31:
            raw -= 2**32
    return raw / register.gain


def encode(register: Register, value: int) -> list[int]:
    """Codifica un valore intero nelle word Modbus da scrivere."""
    if not register.writable:
        raise ValueError(f"Registro {register.address} non scrivibile")
    if value < 0:
        raise ValueError(f"Registro {register.address}: valore negativo non ammesso")
    if register.reg_type is RegType.UINT16:
        if value > 0xFFFF:
            raise ValueError(f"Registro {register.address}: valore fuori range uint16")
        return [value]
    if value > 0xFFFFFFFF:
        raise ValueError(f"Registro {register.address}: valore fuori range uint32")
    return [(value >> 16) & 0xFFFF, value & 0xFFFF]
