"""RD-05 / ADR-03 — Decimal para dinheiro."""

from decimal import Decimal

import pytest

from certgen.domain.dinheiro import DinheiroInvalido, e_positivo, para_dinheiro, para_json


def test_rd_05_float_e_rejeitado():
    with pytest.raises(DinheiroInvalido):
        para_dinheiro(150000.0)


def test_rd_05_int_str_decimal_sao_aceitos_com_duas_casas():
    assert para_dinheiro(150000) == Decimal("150000.00")
    assert para_dinheiro("18.9") == Decimal("18.90")
    assert para_dinheiro("18,90") == Decimal("18.90")
    assert para_dinheiro(Decimal("5000")) == Decimal("5000.00")


def test_rd_13_none_permanece_none():
    assert para_dinheiro(None) is None
    assert para_json(None) is None


def test_def_11_linha_branca_string_vazia_vira_ausente():
    assert para_dinheiro("") is None
    assert para_dinheiro("   ") is None


def test_rd_05_serializacao_json_e_string_decimal():
    assert para_json(Decimal("150000")) == "150000.00"
    assert para_json(Decimal("18.9")) == "18.90"


def test_rn_01_e_positivo_define_contratada():
    assert e_positivo(Decimal("0.01"))
    assert not e_positivo(Decimal("0"))
    assert not e_positivo(None)


def test_rd_05_texto_nao_numerico_falha_alto():
    with pytest.raises(DinheiroInvalido):
        para_dinheiro("abc")
