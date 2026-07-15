from datetime import datetime

import pytest

from hems.modbus import registers as regs
from hems.modbus.registers import decode, encode


def test_decode_uint16_soc_gain():
    # 500 -> 50.0% (passo 0.1%)
    assert decode(regs.BATTERY_SOC, [500]) == 50.0


def test_decode_int32_positive():
    # 3000 W di produzione
    assert decode(regs.INVERTER_ACTIVE_POWER, [0, 3000]) == 3000


def test_decode_int32_negative():
    # -1500 W (prelievo dalla rete) in complemento a due su 32 bit
    raw = (-1500) & 0xFFFFFFFF
    words = [(raw >> 16) & 0xFFFF, raw & 0xFFFF]
    assert decode(regs.METER_ACTIVE_POWER, words) == -1500


def test_decode_wrong_word_count():
    with pytest.raises(ValueError):
        decode(regs.INVERTER_ACTIVE_POWER, [0])


def test_encode_uint16():
    assert encode(regs.FORCE_COMMAND, 2) == [2]


def test_encode_uint32_split():
    assert encode(regs.FORCED_CHARGE_POWER, 0x0001_0002) == [1, 2]


def test_encode_rejects_readonly_register():
    with pytest.raises(ValueError):
        encode(regs.BATTERY_SOC, 1)


def test_encode_rejects_out_of_range():
    with pytest.raises(ValueError):
        encode(regs.FORCE_COMMAND, 70000)
    with pytest.raises(ValueError):
        encode(regs.FORCE_COMMAND, -1)
