"""Fase 2, aceitacao: JSON de certificado REAL valida; nulos como null; 11 coberturas; avisos."""

from __future__ import annotations

import json

import pytest

from certgen.adapters.firebird import conexao
from certgen.adapters.firebird.repositorio import RepositorioFirebird
from certgen.application.emitir_certificados import OpcoesEmissao, emitir_lote
from certgen.config.settings import ConfiguracaoAusente
from certgen.domain.certificado import ChaveLote
from certgen.serialize.json_certificado import erros_de_validacao

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def repo():
    try:
        conexao.verificar_conexao()
    except (ConfiguracaoAusente, conexao.ErroConexao) as exc:
        pytest.skip(f"Firebird indisponivel: {exc}")
    yield RepositorioFirebird()
    conexao.esvaziar_pools()


def _lote(repo, adm, apolice, fatura):
    for a in repo.listar_apolices(adm, None):
        if a.apolice == apolice and fatura in repo.listar_faturas(adm, apolice, a.seq, None):
            return ChaveLote(adm, apolice, a.seq, fatura)
    pytest.fail("lote de referencia nao encontrado")


def test_fase_2_fatura_380819_imodata(repo, tmp_path):
    rel = emitir_lote(repo, _lote(repo, "0000001192", "13008", 380819), OpcoesEmissao(tmp_path))
    assert rel.falhas == [], rel.resumo()
    assert len(rel.emitidos) == 5  # contagem verificada no banco em 03/09/2026
    ref = next(e for e in rel.emitidos if "CF1DI-AP602" in e.json_path.name)
    assert ref.json_path.name == "0_33016330725_0004_13008_CF1DI-AP602_380819.json"
    doc = json.loads(ref.json_path.read_text(encoding="utf-8"))
    assert erros_de_validacao(doc) == []
    assert len(doc["coberturas"]) == 11
    assert doc["segurado"]["nome"].startswith("JORGE EDUARDO")
    assert doc["administradora"]["abreviacao"] is None
    assert doc["contrato"]["sucursal"] == "RJ"
    assert doc["_meta"]["faz_tudo_lar"] is True
    assert {a["codigo"] for a in doc["_meta"]["avisos"]} >= {"ABREV_ADM_AUSENTE", "PORTAL_AUSENTE"}


def test_fase_2_fatura_381066_protest_excecao_rn_03_1(repo, tmp_path):
    rel = emitir_lote(repo, _lote(repo, "0000000019", "15008", 381066), OpcoesEmissao(tmp_path))
    assert rel.falhas == [], rel.resumo()
    nomes = {e.json_path.name for e in rel.emitidos}
    assert "0_05554363733_0001_15008_3082-01-AP1302_381066.json" in nomes
    assert "0_14529138704_0001_15008_3082-01-AP1101_381066.json" in nomes
    alvo = next(e for e in rel.emitidos if "3082-01-AP1302" in e.json_path.name)
    doc = json.loads(alvo.json_path.read_text(encoding="utf-8"))
    assert erros_de_validacao(doc) == []
    assert doc["produto"]["codigo"] == "0001"
    assert doc["vigencia"]["fim"] is None  # DEF-06
    assert doc["certificado"]["cod_0800"] == "3082/01/AP 1302 19PAEL"  # RN-20
    codigos = {a["codigo"] for a in doc["_meta"]["avisos"]}
    assert {"PRODUTO_POR_EXCECAO", "FINAL_VIG_AUSENTE"} <= codigos
