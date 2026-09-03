"""ADR-05/ADR-06 — template unico renderiza a referencia; Faz Tudo Lar opcional; RF-10."""

from datetime import date

import pytest

from certgen.adapters.firebird.repositorio import RepositorioFirebird
from certgen.render.html import DadosRender, imagens_base64, renderizar_html
from tests.unit.test_repositorio_mapeamento import LINHA_13008

DADOS = DadosRender(data_emissao=date(2026, 9, 3), exibe_premio=True)


@pytest.fixture(scope="module")
def repo():
    return RepositorioFirebird()


@pytest.fixture(scope="module")
def html(repo):
    return renderizar_html(repo._montar(LINHA_13008), DADOS)


def test_imagens_do_pdf_de_referencia_estao_embutidas():
    imgs = imagens_base64()
    esperadas = {
        "logo_fedcorp", "cartao_virtual", "selo_lider",
        "logo_bradesco", "selo_clube", "faixa_rodape",
    }  # fmt: skip
    assert esperadas <= set(imgs)
    assert all(v.startswith("data:image/") for v in imgs.values())


def test_adr_06_valores_da_referencia_13008_no_html(html):
    for esperado in (
        "DEMONSTRATIVO", "Total <b>Conteúdo</b>",
        "JORGE EDUARDO MONT SERRAT", "330.163.307-25", "AV LUCIO COSTA, 3300 BLOCO 2",
        "BARRA DA TIJUA", "RIO DE JANEIRO", "22630-010", "DIRETORIA IMODATA",
        "01/07/2026", "31/07/2026", "15.414.901282/2014-83", "RJ", "CF1DI/AP.602",
        "03/09/2026", "13008", "40150116/R-ESP", "AP.602",
        "FEDCORP ADMINISTRADORA DE BENEFICIOS LTDA", "IMODATA ADM DE IMOVEIS",
        "R$ 100.000,00", "R$ 10.000,00", "R$ 5.000,00", "R$ 20.000,00",
        "00000202049583", "PREMIO: R$ 18,90", "0800 770 4362", "0800 251 6001",
    ):
        assert esperado in html, esperado


def test_rn_18_bloco_faz_tudo_lar_presente_quando_mondial_1003(html):
    assert "Assistência Faz Tudo Lar" in html
    assert "TROCA DE LÂMPADAS" in html


def test_adr_06_bloco_faz_tudo_lar_opcional(repo):
    sem = renderizar_html(repo._montar({**LINHA_13008, "codigo_assist_mondial": "1002"}), DADOS)
    assert "Faz Tudo Lar" not in sem
    assert "Assistência Residencial Emergencial 24h" in sem  # o resto permanece


def test_adr_06_operador_pode_forcar_ou_remover_o_faz_tudo(repo):
    cert = repo._montar(LINHA_13008)  # mondial 1003 -> derivacao True
    sem = renderizar_html(cert, DadosRender(date(2026, 9, 3), True, faz_tudo_lar=False))
    assert "Assistência Faz Tudo Lar" not in sem
    outro = repo._montar({**LINHA_13008, "codigo_assist_mondial": None})  # derivacao False
    com = renderizar_html(outro, DadosRender(date(2026, 9, 3), True, faz_tudo_lar=True))
    assert "TROCA DE LÂMPADAS" in com


def test_rf_10_premio_opcional(repo):
    dados = DadosRender(date(2026, 9, 3), exibe_premio=False)
    sem = renderizar_html(repo._montar(LINHA_13008), dados)
    assert "PREMIO:" not in sem


def test_def_06_vigencia_ausente_sai_como_travessao(repo):
    h = renderizar_html(repo._montar({**LINHA_13008, "final_vig": date(1899, 12, 30)}), DADOS)
    assert "30/12/1899" not in h
    assert "<span>01/07/2026</span><span>—</span>" in h


def test_rn_01_cobertura_nao_contratada_nao_imprime_valor(repo):
    h = renderizar_html(repo._montar({**LINHA_13008, "rc": None, "resp_civil": None}), DADOS)
    assert "R$ 20.000,00" not in h
    assert "RESPONSABILIDADE CIVIL TERCEIROS" not in h
    assert "Cobertura RC" in h  # a caixa continua, vazia


def test_rn_23_rn_25_rn_26_campos_decididos(html):
    assert ">Plano</div><div class=\"valor\"></div>" in html  # RN-23 vazio
    assert "Código SUSEP da Corretora" in html and "00000202049583" in html  # RN-25
    assert ">SUC.</div><div class=\"valor\">RJ</div>" in html  # RN-26


def test_logo_da_seguradora_bradesco_e_caixa_vazia_para_desconhecida(repo):
    com = renderizar_html(repo._montar({**LINHA_13008, "cod_seguradora": "0000000104"}), DADOS)
    sem = renderizar_html(repo._montar({**LINHA_13008, "cod_seguradora": "0000000109"}), DADOS)
    assert 'alt="Seguradora"' in com
    assert 'alt="Seguradora"' not in sem


def test_nunca_imprime_none(html):
    assert ">None<" not in html


def test_rnf_12_html_autocontido():
    imgs = imagens_base64()
    assert all("base64," in v for v in imgs.values())
