"""RN-01 — catalogo de 12; RN-02 — COB_INCENDIO recalculada; RD-11 — sempre as 12."""

from decimal import Decimal

import pytest

from certgen.domain.avisos import CodigoAviso
from certgen.domain.cobertura import (
    CATALOGO,
    CODIGOS,
    calcular_cob_incendio,
    montar_coberturas,
)
from certgen.domain.dinheiro import DinheiroInvalido

# Valores do PDF de referencia 0_33016330725_0004_13008_380819 (secao 9.1)
REF_13008 = {
    "INC_PREDIO": Decimal("100000"),
    "INC_CONTEUDO": None,
    "ALUGUEL": Decimal("10000"),
    "RUP_ENCANAMENTO": Decimal("5000"),
    "RC": Decimal("20000"),
}


def test_rn_01_catalogo_tem_exatamente_12_na_ordem_fixa():
    assert len(CATALOGO) == 12
    assert CODIGOS == (
        "INC_PREDIO", "INC_CONTEUDO", "COB_INCENDIO", "ALUGUEL", "RUP_ENCANAMENTO", "RC",
        "RUP_ENC_TER", "RESP_CIVIL", "DANOS_ELETRICOS", "QUEBRA_VIDRO", "LINHA_BRANCA",
        "ACIDENTE_PESSOAL",
    )  # fmt: skip


def test_rd_11_montar_devolve_sempre_as_12_mesmo_com_entrada_parcial():
    cobs, _ = montar_coberturas(REF_13008)
    assert [c.codigo for c in cobs] == list(CODIGOS)


def test_rn_01_nao_contratadas_vem_com_contratada_false_e_is_null():
    cobs, _ = montar_coberturas(REF_13008)
    por = {c.codigo: c for c in cobs}
    assert por["INC_CONTEUDO"].contratada is False
    assert por["INC_CONTEUDO"].importancia_segurada is None
    assert por["QUEBRA_VIDRO"].contratada is False
    assert por["RC"].contratada is True
    assert por["RC"].importancia_segurada == Decimal("20000.00")


def test_rn_01_pdf_omite_is_zero_mas_json_declara():
    cobs, _ = montar_coberturas({"ALUGUEL": Decimal("0")})
    aluguel = next(c for c in cobs if c.codigo == "ALUGUEL")
    assert aluguel.contratada is False
    assert aluguel.imprime_no_pdf is False
    assert aluguel.para_dict()["importancia_segurada"] == "0.00"  # RD-13: zero != null


def test_rn_02_cob_incendio_soma_com_coalesce():
    assert calcular_cob_incendio(None, Decimal("100000")) == Decimal("100000")
    assert calcular_cob_incendio(Decimal("30000"), Decimal("70000")) == Decimal("100000")
    assert calcular_cob_incendio(None, None) == Decimal("0")


def test_def_05_null_nao_zera_o_total_de_incendio():
    cobs, avisos = montar_coberturas(REF_13008)
    inc = next(c for c in cobs if c.codigo == "COB_INCENDIO")
    assert inc.importancia_segurada == Decimal("100000.00")
    assert inc.contratada is True
    assert inc.derivada is True
    assert avisos == []


def test_rn_02_divergencia_com_o_banco_gera_aviso():
    _, avisos = montar_coberturas(REF_13008, cob_incendio_banco=Decimal("0"))
    assert [a.codigo for a in avisos] == [CodigoAviso.COB_INCENDIO_DIVERGENTE]


def test_rn_02_banco_igual_nao_gera_aviso():
    _, avisos = montar_coberturas(REF_13008, cob_incendio_banco=Decimal("100000"))
    assert avisos == []


def test_gap_16_linha_branca_flag_s_n_falha_alto_ate_decisao():
    """No banco LINHA_BRANCA e VARCHAR(1) com 'S'/'N'/'0' (03/09/2026), nao valor.

    Enquanto GAP-16 estiver aberto, receber o flag como dinheiro e erro explicito
    (ADR-04), nunca silenciosamente zero ou nulo.
    """
    for flag in ("S", "N"):
        with pytest.raises(DinheiroInvalido):
            montar_coberturas({"LINHA_BRANCA": flag})
    # '0' e numerico e passa como IS zero, nao contratada — comportamento a rever em GAP-16
    cobs, _ = montar_coberturas({"LINHA_BRANCA": "0"})
    assert next(c for c in cobs if c.codigo == "LINHA_BRANCA").contratada is False


def test_rn_01_codigo_fora_do_catalogo_falha_alto():
    with pytest.raises(KeyError):
        montar_coberturas({"ROUBO": Decimal("1")})


def test_rd_11_para_dict_marca_derivada_so_na_cob_incendio():
    cobs, _ = montar_coberturas(REF_13008)
    dicts = [c.para_dict() for c in cobs]
    assert dicts[2]["codigo"] == "COB_INCENDIO" and dicts[2]["derivada"] is True
    assert all("derivada" not in d for i, d in enumerate(dicts) if i != 2)
