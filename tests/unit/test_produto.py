"""RN-03, RN-03.1, RN-03.2, RN-03.3 — derivacao do produto a partir de produtos.toml."""

import pytest

from certgen.domain.avisos import CodigoAviso
from certgen.domain.produto import CatalogoInvalido, CatalogoProdutos, ProdutoIndeterminado


@pytest.fixture(scope="module")
def catalogo() -> CatalogoProdutos:
    return CatalogoProdutos.carregar()


def test_rn_03_catalogo_tem_os_sete_produtos_do_comentario_1202_1208(catalogo):
    assert sorted(p.codigo for p in catalogo.produtos) == [
        "0001", "0002", "0003", "0004", "0005", "0006", "0007",
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("apolice", "produto", "curta"),
    [
        ("4008", "0001", "RESIDENCIAL"),
        ("9008", "0001", "RESIDENCIAL"),  # so no fluxo em massa do legado
        ("10008", "0001", "RESIDENCIAL"),  # idem
        ("5008", "0002", "COMERCIAL"),
        ("13008", "0004", "RUPTURA"),
        ("14008", "0004", "RUPTURA"),  # idem
        ("15008", "0004", "RUPTURA"),  # idem — o DEF-09 dos arquivos de referencia
        ("6008", "0006", "LOC-RES"),
        ("7008", "0007", "LOC-COM"),
    ],
)
def test_rn_03_mapa_e_a_uniao_dos_dois_fluxos(catalogo, apolice, produto, curta):
    r = catalogo.resolver(apolice)
    assert r.produto.codigo == produto
    assert r.produto.descricao_curta == curta
    assert r.aviso is None


def test_rn_03_1_administradora_0000000019_na_15008_emite_residencial(catalogo):
    r = catalogo.resolver("15008", administradora="0000000019")
    assert r.produto.codigo == "0001"
    assert r.regra.especifica


def test_rd_23_excecao_registra_aviso_produto_por_excecao(catalogo):
    r = catalogo.resolver("15008", administradora="0000000019")
    assert r.aviso is not None
    assert r.aviso.codigo is CodigoAviso.PRODUTO_POR_EXCECAO
    assert r.avisos == [r.aviso]


def test_rn_03_2_outra_administradora_na_15008_cai_na_regra_geral(catalogo):
    r = catalogo.resolver("15008", administradora="0000004691")
    assert r.produto.codigo == "0004"
    assert r.aviso is None


def test_rn_03_3_apolice_desconhecida_aborta_nomeando_a_apolice(catalogo):
    with pytest.raises(ProdutoIndeterminado) as exc:
        catalogo.resolver("99999")
    assert "99999" in str(exc.value)
    assert exc.value.apolice == "99999"


def test_def_09_apolice_desconhecida_nao_herda_produto_anterior(catalogo):
    catalogo.resolver("13008")  # "selecao anterior"
    with pytest.raises(ProdutoIndeterminado):
        catalogo.resolver("99999")


def test_rn_04_produtos_de_locacao_sao_0006_e_0007(catalogo):
    assert {p.codigo for p in catalogo.produtos if p.locacao} == {"0006", "0007"}


def test_gap_14_produtos_0003_e_0005_existem_mas_nao_sao_emissiveis(catalogo):
    assert catalogo.produto("0003").emissivel is False
    assert catalogo.produto("0005").emissivel is False
    assert all(catalogo.produto(r.produto).emissivel for r in catalogo.regras)


def test_rn_03_2_regra_para_produto_inexistente_falha_na_carga():
    with pytest.raises(CatalogoInvalido):
        CatalogoProdutos.de_dict(
            {
                "produto": [
                    {"codigo": "0001", "descricao": "x", "descricao_curta": "X"},
                ],
                "regra": [{"apolice": "4008", "produto": "0009"}],
            }
        )


def test_rn_03_2_regra_duplicada_falha_na_carga():
    with pytest.raises(CatalogoInvalido):
        CatalogoProdutos.de_dict(
            {
                "produto": [{"codigo": "0001", "descricao": "x", "descricao_curta": "X"}],
                "regra": [
                    {"apolice": "4008", "produto": "0001"},
                    {"apolice": "4008", "produto": "0001"},
                ],
            }
        )


def test_gap_14_regra_para_produto_nao_emissivel_falha_na_carga():
    with pytest.raises(CatalogoInvalido):
        CatalogoProdutos.de_dict(
            {
                "produto": [
                    {"codigo": "0003", "descricao": "x", "descricao_curta": "X", "emissivel": False}
                ],
                "regra": [{"apolice": "4008", "produto": "0003"}],
            }
        )
