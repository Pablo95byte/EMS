from datetime import datetime

import pytest

from hems.datalake.gme import parse_mgp_xml

SAMPLE_XML = """<?xml version="1.0" encoding="utf-8"?>
<NewDataSet>
  <Prezzi>
    <Data>20260310</Data>
    <Mercato>MGP</Mercato>
    <Ora>1</Ora>
    <PUN>95,123456</PUN>
    <NORD>93,50</NORD>
  </Prezzi>
  <Prezzi>
    <Data>20260310</Data>
    <Mercato>MGP</Mercato>
    <Ora>2</Ora>
    <PUN>88,00</PUN>
    <NORD>86,10</NORD>
  </Prezzi>
</NewDataSet>
"""


def test_parse_pun():
    prices = parse_mgp_xml(SAMPLE_XML, "PUN")
    assert prices[datetime(2026, 3, 10, 0)] == pytest.approx(95.123456)
    assert prices[datetime(2026, 3, 10, 1)] == pytest.approx(88.0)


def test_parse_zona_nord():
    prices = parse_mgp_xml(SAMPLE_XML, "NORD")
    assert prices[datetime(2026, 3, 10, 0)] == pytest.approx(93.5)


def test_zona_inesistente():
    with pytest.raises(ValueError):
        parse_mgp_xml(SAMPLE_XML, "SICI")
