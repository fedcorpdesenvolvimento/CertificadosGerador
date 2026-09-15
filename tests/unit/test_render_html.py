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
    esperadas = {"logo_fedcorp", "cartao_virtual", "selo_lider", "selo_clube", "faixa_rodape"}
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
    assert "KIT FIXAÇÃO" in html
    # RD-34 (15/09/2026): ultima linha do bloco aponta para o site da assistencia
    bloco = html.split("Assistência Faz Tudo Lar", 1)[1].split("Clube de Vantagens", 1)[0]
    assert "Consulte todas as informações em https://assistencia.grupofedcorp.com.br/" in bloco
    assert bloco.index("2 SERVIÇOS / ANO") < bloco.index("Consulte todas as informações")


def test_adr_06_bloco_faz_tudo_lar_opcional(repo):
    linha = {**LINHA_13008, "codigo_assist_mondial": "1002", "rup_encanamento": None}  # RN-18a
    sem = renderizar_html(repo._montar(linha), DADOS)
    assert "Faz Tudo Lar" not in sem
    assert "Assistência Residencial Emergencial 24h" in sem  # o resto permanece


def test_adr_06_operador_pode_forcar_ou_remover_o_faz_tudo(repo):
    cert = repo._montar(LINHA_13008)  # mondial 1003 -> derivacao True
    sem = renderizar_html(cert, DadosRender(date(2026, 9, 3), True, faz_tudo_lar=False))
    assert "Assistência Faz Tudo Lar" not in sem
    outro = repo._montar(
        {**LINHA_13008, "codigo_assist_mondial": None, "rup_encanamento": None}
    )  # derivacao False (RN-18 e RN-18a)
    com = renderizar_html(outro, DadosRender(date(2026, 9, 3), True, faz_tudo_lar=True))
    assert "KIT FIXAÇÃO" in com


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
    assert "Cobertura RC" in h  # a caixa continua, vazia


LINHAS_RUPTURA = (
    "RUPTURA DE TUBULAÇÕES HIDRÁULICAS",
    "RESPONSABILIDADE CIVIL TERCEIROS",
    "Para maiores informações sobre como funcionam as coberturas",
)


def test_rn_27_bloco_ruptura_aparece_quando_rup_encanamento_maior_que_zero(html):
    for linha in LINHAS_RUPTURA:
        assert linha in html, linha
    assert "R$ 5.000,00" in html and "R$ 20.000,00" in html


@pytest.mark.parametrize("valor", [None, "0", "0.00"])
def test_rn_27_bloco_ruptura_inibido_sem_valor(repo, valor):
    h = renderizar_html(repo._montar({**LINHA_13008, "rup_encanamento": valor}), DADOS)
    for linha in LINHAS_RUPTURA:
        assert linha not in h, linha
    assert "O Seguro cobre danos causados por Incêndio" in h  # o texto basico permanece


def test_rn_27_aviso_quando_produto_0004_sem_ruptura_ou_vice_versa(repo):
    c = repo._montar({**LINHA_13008, "rup_encanamento": None})  # 13008 -> 0004 sem valor
    assert "RUPTURA_INCONSISTENTE" in {str(a.codigo) for a in c.todos_avisos()}
    c2 = repo._montar({**LINHA_13008, "apolice": "4008"})  # 0001 com ruptura 5.000
    assert "RUPTURA_INCONSISTENTE" in {str(a.codigo) for a in c2.todos_avisos()}
    c3 = repo._montar(LINHA_13008)  # 0004 com ruptura: coerente
    assert "RUPTURA_INCONSISTENTE" not in {str(a.codigo) for a in c3.todos_avisos()}


def test_rn_23_rn_25_rn_26_campos_decididos(html):
    assert ">Plano</div><div class=\"valor\">RES</div>" in html  # RN-23: tipo_categoria R
    assert "Código SUSEP da Corretora" in html and "00000202049583" in html  # RN-25
    assert ">SUC.</div><div class=\"valor\">RJ</div>" in html  # RN-26


def test_rn_28_logo_bradesco_e_caixa_vazia_para_desconhecida(repo):
    com = renderizar_html(repo._montar({**LINHA_13008, "cod_seguradora": "0000000109"}), DADOS)
    sem = renderizar_html(repo._montar({**LINHA_13008, "cod_seguradora": "0000000004"}), DADOS)
    assert 'alt="Bradesco Seguros"' in com
    assert "<img" not in sem.split('class="caixa seguradora"')[1].split("</div>")[0]


def test_nunca_imprime_none(html):
    assert ">None<" not in html


def test_rnf_12_html_autocontido():
    imgs = imagens_base64()
    assert all("base64," in v for v in imgs.values())


def test_rn_23_plano_com_para_tipo_categoria_nao_residencial(repo):
    h = renderizar_html(repo._montar({**LINHA_13008, "tipo_categoria": "C"}), DADOS)
    assert '>Plano</div><div class="valor">COM</div>' in h


def test_rd_32_cobertura_incendio_predio_abaixo_da_cobertura_incendio(html, repo):
    pos_inc = html.index(">Cobertura Incêndio</div>")
    pos_predio = html.index(">Cobertura Incêndio Prédio</div>")
    pos_0800 = html.index("Ao solicitar a Assitência 0800")
    assert pos_inc < pos_predio < pos_0800  # a caixa 0800 desceu
    caixa = html[pos_predio:].split("</div></div>")[0]
    assert "R$ 100.000,00" in caixa  # inc_predio da referencia
    so_conteudo = {"inc_predio": None, "inc_conteudo": "100000", "cob_incendio": "100000"}
    sem = renderizar_html(repo._montar({**LINHA_13008, **so_conteudo}), DADOS)
    inicio = sem.index(">Cobertura Incêndio Prédio</div>")
    assert '<div class="valor"></div>' in sem[inicio : inicio + 120]  # caixa presente, vazia


def test_rd_33_valores_do_cartao_maiores_exceto_endereco(html):
    assert ".cartao .campo .valor { font-size: 7.5pt" in html
    assert ".cartao .campo .valor.endereco { font-size: 5.5pt" in html
    assert '<div class="valor endereco">AV LUCIO COSTA' in html


def test_rn_18a_ruptura_imprime_faz_tudo_lar_sem_mondial_1003(repo):
    h = renderizar_html(repo._montar({**LINHA_13008, "codigo_assist_mondial": "1002"}), DADOS)
    assert "Assistência Faz Tudo Lar" in h
    linha = {**LINHA_13008, "codigo_assist_mondial": "1002", "rup_encanamento": None}
    assert "Faz Tudo Lar" not in renderizar_html(repo._montar(linha), DADOS)
