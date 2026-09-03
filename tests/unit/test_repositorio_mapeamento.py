"""Mapeamento linha canonica -> Certificado, sem banco (RD-24, RN-03, RD-23, DEF-06)."""

from datetime import date
from decimal import Decimal

import pytest

from certgen.adapters.firebird.repositorio import RepositorioFirebird
from certgen.domain.avisos import CodigoAviso
from certgen.domain.produto import ProdutoIndeterminado

# Linha como a consulta canonica devolve para o PDF de referencia 13008/380819 (secao 9.1)
LINHA_13008 = {
    "nome_adm": "IMODATA ADM DE IMOVEIS E SERVICOS EMPRESARIAIS",
    "abrev_adm": None,
    "administradora": "0000004691",
    "apolice": "13008",
    "seq": 0,
    "fatura": 380819,
    "endosso": "01112380819",
    "cod_seguradora": "1",
    "beneficiario": "JORGE EDUARDO MONT SERRAT",
    "codigo_pedido_port": None,
    "documento_seg": "33016330725",
    "inicio_vig": date(2026, 7, 1),
    "final_vig": date(2026, 7, 31),
    "endereco": "AV LUCIO COSTA, 3300 BLOCO 2",
    "unidade": "AP.602",
    "cep": "22630010",
    "uf": "RJ",
    "cidade": "RIO DE JANEIRO",
    "bairro": "BARRA DA TIJUA",
    "nome_cond": "DIRETORIA IMODATA",
    "apolice_seguradora": "40150116/R-ESP",
    "proc_susep": "15.414.901282/2014-83",
    "sucursal": "RJ",
    "certificado": "CF1DI/AP.602",
    "inc_conteudo": None,
    "inc_predio": Decimal("100000.00"),
    "aluguel": Decimal("10000.00"),
    "cob_incendio": Decimal("100000.00"),
    "premio": Decimal("18.90"),
    "codigo_assist_mondial": "1003",
    "cod_cat": "1",
    "cod_0800": "CF1DI/AP.602 ",
    "quebra_vidro": None,
    "rc": Decimal("20000.00"),
    "danos_eletricos": None,
    "resp_civil": None,
    "rup_encanamento": Decimal("5000.00"),
    "rup_enc_ter": None,
    "acidente_pessoal": None,
}


@pytest.fixture(scope="module")
def repo() -> RepositorioFirebird:
    return RepositorioFirebird()


def test_rd_24_linha_canonica_vira_certificado_completo(repo):
    c = repo._montar(LINHA_13008)
    assert c.chave.certificado == "CF1DI/AP.602"
    assert c.chave.cpf_cnpj == "33016330725"
    assert c.produto.codigo == "0004"
    assert c.segurado_nome == "JORGE EDUARDO MONT SERRAT"
    assert c.vigencia.fim == date(2026, 7, 31)
    assert c.premio == Decimal("18.90")
    assert c.contrato.apolice_seguradora == "40150116/R-ESP"
    assert c.endosso.faz_tudo_lar is True
    assert c.endosso.locacao is False
    assert c.contexto_template(exibe_premio=True).nome == "incendio_ruptura_faz_tudo"


def test_rn_01_rd_11_onze_coberturas_com_as_contratadas_do_pdf(repo):
    c = repo._montar(LINHA_13008)
    assert len(c.coberturas) == 11
    contratadas = {x.codigo: x.importancia_segurada for x in c.coberturas if x.contratada}
    assert contratadas == {
        "COB_INCENDIO": Decimal("100000.00"),
        "INC_PREDIO": Decimal("100000.00"),
        "ALUGUEL": Decimal("10000.00"),
        "RUP_ENCANAMENTO": Decimal("5000.00"),
        "RC": Decimal("20000.00"),
    }


def test_rd_23_avisos_da_referencia_13008(repo):
    codigos = {a.codigo for a in repo._montar(LINHA_13008).todos_avisos()}
    assert codigos == {CodigoAviso.ABREV_ADM_AUSENTE, CodigoAviso.PORTAL_AUSENTE}


def test_rn_20_cod_0800_recomposto_sem_abrev(repo):
    c = repo._montar(LINHA_13008)
    assert c.cod_0800 == "CF1DI/AP.602"
    assert c.cod_0800_banco == "CF1DI/AP.602"  # strip do espaco que o COALESCE('') deixa


def test_rn_03_1_referencia_15008_da_administradora_19_emite_0001_com_aviso(repo):
    linha = {
        **LINHA_13008,
        "administradora": "0000000019",
        "apolice": "15008",
        "fatura": 381066,
        "certificado": "3082/01/AP 1302",
        "documento_seg": "05554363733",
        "final_vig": date(1899, 12, 30),
        "codigo_assist_mondial": None,
    }
    c = repo._montar(linha)
    assert c.produto.codigo == "0001"
    codigos = {a.codigo for a in c.todos_avisos()}
    assert CodigoAviso.PRODUTO_POR_EXCECAO in codigos
    assert CodigoAviso.FINAL_VIG_AUSENTE in codigos  # DEF-06
    assert c.vigencia.fim is None
    assert c.contexto_template(exibe_premio=False).nome == "incendio"


def test_rn_03_3_apolice_sem_produto_aborta_o_certificado(repo):
    with pytest.raises(ProdutoIndeterminado, match="99999"):
        repo._montar({**LINHA_13008, "apolice": "99999"})


def test_rn_02_divergencia_do_banco_vira_aviso(repo):
    c = repo._montar({**LINHA_13008, "cob_incendio": Decimal("0.00")})
    assert CodigoAviso.COB_INCENDIO_DIVERGENTE in {a.codigo for a in c.todos_avisos()}


def test_rn_26_sucursal_normalizada_e_sem_aviso_quando_uf(repo):
    c = repo._montar({**LINHA_13008, "sucursal": " rj "})
    assert c.contrato.sucursal == "RJ"
    assert CodigoAviso.SUCURSAL_INVALIDA not in {a.codigo for a in c.todos_avisos()}


def test_rn_26_sucursal_suja_gera_aviso_e_e_preservada(repo):
    c = repo._montar({**LINHA_13008, "sucursal": "RK"})
    assert c.contrato.sucursal == "RK"
    assert CodigoAviso.SUCURSAL_INVALIDA in {a.codigo for a in c.todos_avisos()}


def test_rn_25_susep_corretora_vem_da_configuracao(repo):
    assert repo._montar(LINHA_13008).contrato.susep_corretora == "00000202049583"
    outro = RepositorioFirebird(susep_corretora="123")
    assert outro._montar(LINHA_13008).contrato.susep_corretora == "123"


def test_rd_12_documento_com_mascara_e_normalizado_na_chave(repo):
    c = repo._montar({**LINHA_13008, "documento_seg": "330.163.307-25"})
    assert c.chave.cpf_cnpj == "33016330725"
    assert c.documento.formatado == "330.163.307-25"
