# ruff: noqa: E501
"""Fase 3 — PDF real via Chromium. Pula se o Chromium do Playwright nao estiver instalado.

RNF-02: texto selecionavel. RNF-04: espelhamento — todo valor formatado do JSON
aparece no texto extraido do PDF. Tamanho de pagina igual ao PDF de referencia.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from pypdf import PdfReader

from certgen.adapters.firebird.repositorio import RepositorioFirebird
from certgen.render.filtros import data_br, moeda
from certgen.render.html import DadosRender, renderizar_html
from certgen.render.pdf import ALTURA_MM, LARGURA_MM, ErroRenderizacao, RenderizadorPdf
from certgen.serialize.json_certificado import MetaEmissao, certificado_para_dict
from tests.unit.test_repositorio_mapeamento import LINHA_13008

pytestmark = pytest.mark.pdf


@pytest.fixture(scope="module")
def render():
    try:
        with RenderizadorPdf() as r:
            yield r
    except ErroRenderizacao as exc:
        pytest.skip(str(exc))


@pytest.fixture(scope="module")
def cert():
    return RepositorioFirebird()._montar(LINHA_13008)


def _texto(pdf_path) -> str:
    reader = PdfReader(str(pdf_path))
    return "\n".join(p.extract_text() or "" for p in reader.pages), reader


def test_rnf_02_pdf_tem_texto_e_tamanho_da_referencia(render, cert, tmp_path):
    destino = render.renderizar_certificado(cert, DadosRender(date(2026, 9, 3), True), tmp_path / "a.pdf")
    texto, reader = _texto(destino)
    assert len(reader.pages) == 1
    mb = reader.pages[0].mediabox
    assert round(float(mb.width) / 72 * 25.4) == LARGURA_MM
    assert round(float(mb.height) / 72 * 25.4) >= ALTURA_MM  # cresce com o conteudo
    assert "JORGE EDUARDO MONT SERRAT" in texto
    assert "DEMONSTRATIVO" in texto


def test_rnf_04_espelhamento_pdf_json(render, cert, tmp_path):
    meta = MetaEmissao(
        gerado_em=datetime(2026, 9, 3, 10, 0, tzinfo=timezone(timedelta(hours=-3))),
        nome_pdf="x.pdf", pasta_destino="p", exibe_premio=True,
    )  # fmt: skip
    doc = certificado_para_dict(cert, meta)
    destino = render.renderizar_certificado(cert, DadosRender(meta.gerado_em.date(), True), tmp_path / "b.pdf")
    texto, _ = _texto(destino)
    texto_plano = " ".join(texto.split())

    esperados = [
        doc["segurado"]["nome"], doc["segurado"]["documento"]["formatado"],
        doc["certificado"]["numero"], doc["certificado"]["cod_0800"],
        doc["contrato"]["apolice"]["codigo"], doc["contrato"]["apolice"]["numero_seguradora"],
        doc["contrato"]["processo_susep"], doc["contrato"]["sucursal"], doc["contrato"]["susep_corretora"],
        doc["administradora"]["nome"], doc["local_risco"]["endereco"], doc["local_risco"]["condominio"],
        doc["local_risco"]["cidade"], doc["local_risco"]["unidade"],
        data_br(date.fromisoformat(doc["vigencia"]["inicio"])), data_br(date.fromisoformat(doc["vigencia"]["fim"])),
        data_br(date.fromisoformat(doc["certificado"]["data_emissao"])),
        moeda(cert.premio),
    ] + [moeda(c.importancia_segurada) for c in cert.coberturas if c.contratada and c.codigo in {"COB_INCENDIO", "ALUGUEL", "RUP_ENCANAMENTO", "RC"}]
    faltando = [e for e in esperados if " ".join(str(e).split()) not in texto_plano]
    assert not faltando, faltando


def test_adr_06_faz_tudo_opcional_no_pdf(render, tmp_path):
    repo = RepositorioFirebird()
    sem = repo._montar({**LINHA_13008, "codigo_assist_mondial": None})
    destino = render.pdf(renderizar_html(sem, DadosRender(date(2026, 9, 3), True)), tmp_path / "c.pdf")
    texto, _ = _texto(destino)
    assert "Faz Tudo Lar" not in texto
    assert "Clube de Vantagens" in texto
