# ruff: noqa: E501
"""RD-26 — JSON unico do lote (PDFs individuais), chave cpf_cnpj|certificado."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from certgen.application.emitir_certificados import OpcoesEmissao, emitir_lote
from certgen.serialize.json_certificado import JsonInvalido, erros_de_validacao, lote_json_unico
from tests.unit.test_emitir_certificados import LINHA_13008, LINHA_B, LOTE, RepoFalso
from tests.unit.test_emitir_consolidado import _pdf_falso

AGORA = datetime(2026, 9, 3, 14, 22, 7, tzinfo=timezone(timedelta(hours=-3)))


def test_rd_26_um_json_para_o_lote_e_pdfs_individuais(tmp_path):
    op = OpcoesEmissao(pasta_saida=tmp_path, json_unico=True, agora=lambda: AGORA)
    rel = emitir_lote(RepoFalso([LINHA_13008, LINHA_B]), LOTE, op, renderizar_pdf=_pdf_falso)
    assert rel.falhas == []
    pasta = tmp_path / "0000001192" / "072026"
    nomes = sorted(p.name for p in pasta.iterdir())
    assert nomes == [
        "0_05554363733_0004_13008_CF1DI-AP701_380819.pdf",
        "0_33016330725_0004_13008_CF1DI-AP602_380819.pdf",
        "certificados_13008_1_380819_20260903-142207.json",
    ]
    assert all(e.json_path is None and e.pdf_path is not None for e in rel.emitidos)
    assert rel.json_unico == pasta / nomes[2]


def test_rd_26_estrutura_indexada_por_cpf_e_certificado(tmp_path):
    op = OpcoesEmissao(pasta_saida=tmp_path, json_unico=True, agora=lambda: AGORA)
    rel = emitir_lote(RepoFalso([LINHA_13008, LINHA_B]), LOTE, op)
    env = json.loads(rel.json_unico.read_text(encoding="utf-8"))
    assert env["_meta"]["formato"] == "json_unico"
    assert env["_meta"]["chave"] == "cpf_cnpj|certificado"
    assert env["_meta"]["quantidade"] == 2
    assert env["lote"] == {"administradora": "0000001192", "apolice": "13008", "seq": 1, "fatura": 380819}
    assert set(env["certificados"]) == {"33016330725|CF1DI/AP.602", "05554363733|CF1DI/AP.701"}
    item = env["certificados"]["33016330725|CF1DI/AP.602"]
    assert erros_de_validacao(item) == []  # cada item e um certificado completo e valido (RD-15)
    assert item["arquivo"]["pdf"] == "0_33016330725_0004_13008_CF1DI-AP602_380819.pdf"
    assert {a["codigo"] for a in item["_meta"]["avisos"]} >= {"ABREV_ADM_AUSENTE", "PORTAL_AUSENTE"}


def test_rd_26_rf_09_falha_em_um_nao_derruba_o_json_unico(tmp_path):
    ruim = {**LINHA_13008, "certificado": "A:B", "documento_seg": "11111111111"}
    op = OpcoesEmissao(pasta_saida=tmp_path, json_unico=True, agora=lambda: AGORA)
    rel = emitir_lote(RepoFalso([ruim, LINHA_B]), LOTE, op)
    assert len(rel.falhas) == 1 and len(rel.emitidos) == 1
    env = json.loads(rel.json_unico.read_text(encoding="utf-8"))
    assert list(env["certificados"]) == ["05554363733|CF1DI/AP.701"]


def test_rd_26_sem_json_unico_continua_um_json_por_certificado(tmp_path):
    op = OpcoesEmissao(pasta_saida=tmp_path, agora=lambda: AGORA)
    rel = emitir_lote(RepoFalso([LINHA_13008, LINHA_B]), LOTE, op)
    assert all(e.json_path is not None for e in rel.emitidos)
    assert rel.json_unico is None


def test_rd_26_chave_duplicada_e_erro():
    from certgen.adapters.firebird.repositorio import RepositorioFirebird
    from certgen.serialize.json_certificado import MetaEmissao, certificado_para_dict

    c = RepositorioFirebird()._montar(LINHA_13008)
    doc = certificado_para_dict(c, MetaEmissao(AGORA, "x.pdf", "p", True))
    with pytest.raises(JsonInvalido, match="duplicada"):
        lote_json_unico([doc, doc], LOTE, AGORA)
