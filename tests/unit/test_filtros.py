"""RN-14 — formatacao brasileira; DEF-06 travessao; RNF-12 sem locale."""

from datetime import date
from decimal import Decimal

import pytest

from certgen.domain.documento import Documento
from certgen.render.filtros import TRACO, cep, data_br, documento, moeda, texto


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        (Decimal("100000"), "R$ 100.000,00"),
        (Decimal("1234567.89"), "R$ 1.234.567,89"),
        (Decimal("18.9"), "R$ 18,90"),
        (Decimal("0"), "R$ 0,00"),
        (Decimal("999"), "R$ 999,00"),
        (Decimal("-5.5"), "-R$ 5,50"),
    ],
)
def test_rn_14_moeda(valor, esperado):
    assert moeda(valor) == esperado


def test_def_06_ausente_vira_travessao():
    assert moeda(None) == TRACO
    assert data_br(None) == TRACO


def test_rn_14_data():
    assert data_br(date(2026, 7, 1)) == "01/07/2026"


def test_rn_14_cep_valido_e_def_08_cep_invalido_nao_ganha_mascara():
    assert cep("22630010") == "22630-010"
    assert cep("24120-191") == "24120-191"
    assert cep("24.120-191") == "24120-191"  # a mascara invalida do legado e corrigida
    assert cep("1234") == "1234"
    assert cep(None) == ""


def test_rn_14_documento():
    assert documento(Documento.de("33016330725")) == "330.163.307-25"
    assert documento("12345678000195") == "12.345.678/0001-95"
    assert documento("12345") == "12345"
    assert documento(None) == ""


def test_texto_nunca_imprime_none():
    assert texto(None) == ""
    assert texto("x") == "x"
    assert texto(0) == "0"
