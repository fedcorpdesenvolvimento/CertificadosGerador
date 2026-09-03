"""RN-28 — logotipo da seguradora por cod_seguradora, via seguradoras.toml (GAP-20)."""

import pytest

from certgen.adapters.firebird.repositorio import RepositorioFirebird
from certgen.domain.avisos import CodigoAviso
from certgen.domain.seguradora import CatalogoSeguradoras, CatalogoSeguradorasInvalido, Seguradora
from certgen.render.html import DadosRender, logo_seguradora_base64, renderizar_html
from tests.unit.test_render_html import DADOS
from tests.unit.test_repositorio_mapeamento import LINHA_13008


@pytest.fixture(scope="module")
def catalogo():
    return CatalogoSeguradoras.carregar()


@pytest.mark.parametrize(
    ("codigo", "nome", "logo"),
    [
        ("0000000109", "Bradesco Seguros", "bradesco.jpg"),
        ("0000000104", "Alfa Seguradora", "bradesco.jpg"),  # decisao: Alfa imprime Bradesco
        ("0000000108", "HDI Seguros", "hdi.png"),
        ("0000000003", "Sompo Seguros", "hdi.png"),  # decisao: Sompo imprime HDI
        ("0000000006", "Porto Seguro", "porto.png"),
    ],
)
def test_rn_28_mapa_das_decisoes_de_03_09_2026(catalogo, codigo, nome, logo):
    s = catalogo.resolver(codigo)
    assert s is not None and s.nome == nome and s.logo == logo


def test_rn_28_fedcorp_assistance_e_desconhecidos_nao_resolvem(catalogo):
    assert catalogo.resolver("0000000004") is None
    assert catalogo.resolver("9999999999") is None
    assert catalogo.resolver(None) is None


def test_rn_28_catalogo_rejeita_duplicado_e_incompleto():
    with pytest.raises(CatalogoSeguradorasInvalido):
        CatalogoSeguradoras([Seguradora("1", "A", "a.png"), Seguradora("1", "B", "b.png")])
    with pytest.raises(CatalogoSeguradorasInvalido):
        CatalogoSeguradoras([Seguradora("1", "A", "")])


def test_rn_28_certificado_alfa_imprime_bradesco_e_json_traz_o_nome():
    c = RepositorioFirebird()._montar(LINHA_13008)  # cod_seguradora 0000000104 = Alfa
    assert c.contrato.seguradora.nome == "Alfa Seguradora"
    html = renderizar_html(c, DADOS)
    assert 'alt="Alfa Seguradora"' in html and "data:image/jpeg" in html
    assert CodigoAviso.LOGO_SEGURADORA_AUSENTE not in {a.codigo for a in c.todos_avisos()}


def test_rn_28_seguradora_sem_entrada_caixa_vazia_e_aviso():
    c = RepositorioFirebird()._montar({**LINHA_13008, "cod_seguradora": "0000000004"})
    assert c.contrato.seguradora is None
    assert CodigoAviso.LOGO_SEGURADORA_AUSENTE in {a.codigo for a in c.todos_avisos()}
    caixa = renderizar_html(c, DADOS).split('class="caixa seguradora"')[1].split("</div>")[0]
    assert "<img" not in caixa


def test_rn_28_arquivo_de_logo_ainda_ausente_nao_quebra():
    # hdi.png / porto.png ainda nao foram entregues: a caixa sai vazia, sem erro
    assert logo_seguradora_base64("arquivo-que-nao-existe.png") is None
    c = RepositorioFirebird()._montar({**LINHA_13008, "cod_seguradora": "0000000003"})
    html = renderizar_html(c, DadosRender(DADOS.data_emissao, True))
    assert c.contrato.seguradora.nome == "Sompo Seguros"
    assert "Sompo" not in html or logo_seguradora_base64("hdi.png") is not None
