"""RN-11, RN-12, RN-13, RN-17b, RN-19 — nomes de arquivo."""

from datetime import date, datetime
from pathlib import Path

import pytest

from certgen.domain.nomes_arquivo import (
    NomeArquivoInvalido,
    competencia,
    nome_arquivo_certificado,
    nome_consolidado,
    pasta_lote,
    resolver_colisao,
    sanitizar_certificado,
)
from certgen.domain.produto import CatalogoProdutos


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("CF1DI/AP.602", "CF1DI-AP602"),
        ("3082/01/AP 1302", "3082-01-AP1302"),
        ("3082/01/AP 1101", "3082-01-AP1101"),
        ("A\\B|C", "A-B-C"),
    ],
)
def test_rn_17b_sanitizacao_igual_ao_legado(entrada, esperado):
    assert sanitizar_certificado(entrada) == esperado


@pytest.mark.parametrize("ruim", ['A:B', 'A*B', 'A?B', 'A"B', 'A<B', 'A>B', "A\tB", "A\nB"])
def test_rn_17b_rejeita_caracteres_ausentes_da_lista_do_legado(ruim):
    with pytest.raises(NomeArquivoInvalido):
        sanitizar_certificado(ruim)


def test_rn_17b_certificado_vazio_falha():
    with pytest.raises(NomeArquivoInvalido):
        sanitizar_certificado("   ")
    with pytest.raises(NomeArquivoInvalido):
        sanitizar_certificado(". .")


def test_rn_11_padrao_unico_de_seis_campos_referencia_13008():
    nome = nome_arquivo_certificado(0, "33016330725", "0004", "13008", "CF1DI/AP.602", 380819)
    assert nome == "0_33016330725_0004_13008_CF1DI-AP602_380819.pdf"


def test_rn_11_extensao_json():
    nome = nome_arquivo_certificado(
        None, "33016330725", "0004", "13008", "CF1DI/AP.602", 380819, extensao="json"
    )
    assert nome == "0_33016330725_0004_13008_CF1DI-AP602_380819.json"


def test_rn_11_portal_nulo_vira_zero():
    nome = nome_arquivo_certificado(None, "33016330725", "0004", "13008", "X", 1)
    assert nome.startswith("0_")


def test_rn_11_referencias_da_secao_7_2_com_produto_resolvido(arquivos_referencia):
    """Os tres arquivos de referencia, agora com o produto que RN-03 resolve.

    Os dois `15008` saiam sem produto (DEF-09); no sistema novo saem como 0004.
    """
    catalogo = CatalogoProdutos.carregar()
    esperados = {
        "0_33016330725_0004_13008_380819.pdf": "0_33016330725_0004_13008_CF1DI-AP602_380819.pdf",
        "0_05554363733__15008_381066.pdf": "0_05554363733_0004_15008_3082-01-AP1302_381066.pdf",
        "0_14529138704__15008_381066.pdf": "0_14529138704_0004_15008_3082-01-AP1101_381066.pdf",
    }
    for legado, portal, cpf, _prod_legado, apolice, cert, fatura in arquivos_referencia:
        produto = catalogo.resolver(apolice).produto.codigo
        nome = nome_arquivo_certificado(portal, cpf, produto, apolice, cert, fatura)
        assert nome == esperados[legado]


def test_def_09_produto_vazio_passa_a_falhar_explicitamente(arquivos_referencia):
    """0_05554363733__15008_381066.pdf: o campo vazio do legado e erro no sistema novo."""
    legado, portal, cpf, prod_vazio, apolice, cert, fatura = arquivos_referencia[1]
    assert prod_vazio == ""
    with pytest.raises(NomeArquivoInvalido, match="DEF-09"):
        nome_arquivo_certificado(portal, cpf, prod_vazio, apolice, cert, fatura)


@pytest.mark.parametrize("produto", ["4", "04", "RUPTURA", "00041", None])
def test_rn_11_produto_deve_ter_quatro_digitos(produto):
    with pytest.raises(NomeArquivoInvalido):
        nome_arquivo_certificado(0, "33016330725", produto, "13008", "X", 1)


def test_rn_11_cpf_cnpj_apenas_digitos():
    with pytest.raises(NomeArquivoInvalido):
        nome_arquivo_certificado(0, "330.163.307-25", "0004", "13008", "X", 1)
    with pytest.raises(NomeArquivoInvalido):
        nome_arquivo_certificado(0, "", "0004", "13008", "X", 1)


def test_rd_4_2_fatura_e_inteiro():
    with pytest.raises(NomeArquivoInvalido):
        nome_arquivo_certificado(0, "33016330725", "0004", "13008", "X", "380819")  # type: ignore[arg-type]


def test_rn_12_nome_do_consolidado():
    instante = datetime(2026, 9, 3, 14, 22, 7)
    assert nome_consolidado("13008", 0, 380819, instante) == (
        "certificados_13008_0_380819_20260903-142207.pdf"
    )
    assert nome_consolidado("13008", 0, 380819, instante, "json").endswith(".json")


def test_rn_19_competencia_com_zero_a_esquerda():
    assert competencia(date(2026, 7, 15)) == "072026"
    assert competencia(date(2026, 12, 1)) == "122026"


def test_def_16_competencia_sem_data_e_erro_nao_121899():
    with pytest.raises(NomeArquivoInvalido):
        competencia(None)


def test_rn_19_pasta_lote():
    assert pasta_lote(Path("C:/certificados"), "0000004691", date(2026, 7, 1)) == Path(
        "C:/certificados/0000004691/072026"
    )


def test_rn_13_sem_colisao_devolve_o_proprio_caminho():
    alvo = Path("saida/a.pdf")
    assert resolver_colisao(alvo, existe=lambda _: False) == (alvo, False)


def test_rn_13_colisao_acrescenta_sufixo_n_sem_sobrescrever():
    ocupados = {Path("saida/a.pdf"), Path("saida/a (1).pdf")}
    final, colidiu = resolver_colisao(Path("saida/a.pdf"), existe=lambda p: p in ocupados)
    assert final == Path("saida/a (2).pdf")
    assert colidiu is True
