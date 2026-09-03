# ruff: noqa: E501
"""RF-07 (Individuais desmarcado) / RF-08 / RN-12 / DEF-15 — modo consolidado, com PDF falso."""

import json
from datetime import datetime, timedelta, timezone

from certgen.application.emitir_certificados import OpcoesEmissao, emitir_lote
from tests.unit.test_emitir_certificados import LINHA_13008, LINHA_B, LOTE, RepoFalso

AGORA = datetime(2026, 9, 3, 14, 22, 7, tzinfo=timezone(timedelta(hours=-3)))


def _pdf_falso(cert, meta, destino):
    # PDF minimo valido para o pypdf conseguir concatenar
    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    with destino.open("wb") as fh:
        w.write(fh)
    return destino


def test_rf_07_consolidado_grava_um_pdf_e_um_json(tmp_path):
    op = OpcoesEmissao(pasta_saida=tmp_path, individuais=False, agora=lambda: AGORA)
    rel = emitir_lote(RepoFalso([LINHA_13008, LINHA_B]), LOTE, op, renderizar_pdf=_pdf_falso)
    assert rel.falhas == []
    pasta = tmp_path / "0000001192" / "072026"
    nomes = sorted(p.name for p in pasta.iterdir())
    assert nomes == [
        "certificados_13008_1_380819_20260903-142207.json",
        "certificados_13008_1_380819_20260903-142207.pdf",
    ]  # RN-12; individuais descartados; pasta temporaria removida
    assert rel.consolidado_pdf == pasta / nomes[1]


def test_rf_08_rd_14_json_consolidado_mesma_ordem_e_sem_meta_proprio(tmp_path):
    op = OpcoesEmissao(pasta_saida=tmp_path, individuais=False, agora=lambda: AGORA)
    rel = emitir_lote(RepoFalso([LINHA_13008, LINHA_B]), LOTE, op, renderizar_pdf=_pdf_falso)
    env = json.loads(rel.consolidado_json.read_text(encoding="utf-8"))
    assert env["_meta"] == {"quantidade": 2, "arquivo_pdf": rel.consolidado_pdf.name}
    assert env["lote"] == {"administradora": "0000001192", "apolice": "13008", "seq": 1,
                           "fatura": 380819, "competencia": "072026"}  # fmt: skip
    assert [c["certificado"]["numero"] for c in env["certificados"]] == ["CF1DI/AP.602", "CF1DI/AP.701"]
    assert all("_meta" not in c for c in env["certificados"])


def test_def_15_consolidado_pdf_tem_uma_pagina_por_certificado(tmp_path):
    from pypdf import PdfReader

    op = OpcoesEmissao(pasta_saida=tmp_path, individuais=False, agora=lambda: AGORA)
    rel = emitir_lote(RepoFalso([LINHA_13008, LINHA_B]), LOTE, op, renderizar_pdf=_pdf_falso)
    assert len(PdfReader(str(rel.consolidado_pdf)).pages) == 2


def test_rf_09_falha_em_um_nao_derruba_o_consolidado(tmp_path):
    ruim = {**LINHA_13008, "certificado": "A:B", "documento_seg": "11111111111"}
    op = OpcoesEmissao(pasta_saida=tmp_path, individuais=False, agora=lambda: AGORA)
    rel = emitir_lote(RepoFalso([ruim, LINHA_B]), LOTE, op, renderizar_pdf=_pdf_falso)
    assert len(rel.falhas) == 1 and len(rel.emitidos) == 1
    assert rel.consolidado_pdf is not None


def test_rf_07_consolidado_sem_renderizador_gera_so_json(tmp_path):
    op = OpcoesEmissao(pasta_saida=tmp_path, individuais=False, agora=lambda: AGORA)
    rel = emitir_lote(RepoFalso([LINHA_13008]), LOTE, op)
    assert rel.consolidado_json is not None and rel.consolidado_pdf is None
