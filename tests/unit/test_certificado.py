"""RD-01/RD-21, RN-04, RN-18, RN-20, DEF-06, ADR-05 — entidades do certificado."""

from datetime import date
from decimal import Decimal

import pytest

from certgen.domain.avisos import CodigoAviso
from certgen.domain.certificado import (
    DATA_ZERO_DELPHI,
    Administradora,
    Certificado,
    ChaveCertificado,
    ContextoEndosso,
    ContextoTemplate,
    Contrato,
    LocalRisco,
    Marca,
    Vigencia,
    marca_para_apolice,
    plano_para_tipo_categoria,
)
from certgen.domain.cobertura import montar_coberturas
from certgen.domain.documento import Documento
from certgen.domain.produto import CatalogoProdutos

CATALOGO = CatalogoProdutos.carregar()


def _certificado_13008(**sobrescreve) -> Certificado:
    """O certificado do PDF de referencia 0_33016330725_0004_13008_380819 (9.1)."""
    coberturas, avisos = montar_coberturas(
        {
            "INC_PREDIO": Decimal("100000"),
            "ALUGUEL": Decimal("10000"),
            "RUP_ENCANAMENTO": Decimal("5000"),
            "RC": Decimal("20000"),
        }
    )
    base = dict(
        chave=ChaveCertificado("0000001192", "13008", 0, 380819, "CF1DI/AP.602", "33016330725"),
        administradora=Administradora(
            "0000001192", "IMODATA ADM DE IMOVEIS E SERVICOS EMPRESARIAIS", None
        ),
        contrato=Contrato(
            apolice="13008",
            seq=0,
            fatura=380819,
            endosso="380819",
            cod_seguradora="1",
            apolice_seguradora="40150116/R-ESP",
            processo_susep="15.414.901282/2014-83",
            codigo_pedido_porto=None,
            sucursal="RJ",
        ),
        produto=CATALOGO.resolver("13008").produto,
        segurado_nome="JORGE EDUARDO MONT SERRAT",
        documento=Documento.de("33016330725"),
        vigencia=Vigencia.de(date(2026, 7, 1), date(2026, 7, 31)),
        local_risco=LocalRisco(
            "AV LUCIO COSTA, 3300 BLOCO 2", "AP.602", "DIRETORIA IMODATA",
            "BARRA DA TIJUA", "RIO DE JANEIRO", "RJ", "22630010",
        ),  # fmt: skip
        coberturas=coberturas,
        premio=Decimal("18.90"),
        endosso=ContextoEndosso(endosso="380819", cod_cat=None, codigo_assist_mondial="1003"),
        cod_0800_banco="CF1DI/AP.602 ",
        avisos=avisos,
    )
    base.update(sobrescreve)
    return Certificado(**base)


# ------------------------------------------------------------------ chave
def test_rd_01_chave_nao_inclui_codigo_pedido_port():
    campos = set(ChaveCertificado.__dataclass_fields__)
    assert "codigo_pedido_port" not in campos and "codigo_pedido_porto" not in campos


def test_rd_21_chave_inclui_cpf_cnpj_para_desambiguar_rd_22():
    a = ChaveCertificado("adm", "15008", 0, 381066, "3082/01/AP 1302", "05554363733")
    b = ChaveCertificado("adm", "15008", 0, 381066, "3082/01/AP 1101", "14529138704")
    assert a != b
    assert a.lote == b.lote


# ---------------------------------------------------------------- vigencia
def test_def_06_zero_delphi_e_ausente_com_aviso():
    v = Vigencia.de(date(2026, 7, 1), DATA_ZERO_DELPHI)
    assert v.fim is None
    assert [a.codigo for a in v.avisos()] == [CodigoAviso.FINAL_VIG_AUSENTE]


def test_def_06_final_vig_nula_tambem_gera_aviso():
    assert Vigencia.de(date(2026, 7, 1), None).avisos()[0].codigo is CodigoAviso.FINAL_VIG_AUSENTE


def test_def_06_vigencia_completa_sem_aviso():
    assert Vigencia.de(date(2026, 7, 1), date(2026, 7, 31)).avisos() == []


# ------------------------------------------------------------------ endosso
def test_rn_04_cod_cat_3_ou_4_e_locacao():
    assert ContextoEndosso("1", "3", None).locacao
    assert ContextoEndosso("1", "4", None).locacao
    assert not ContextoEndosso("1", "1", None).locacao
    assert not ContextoEndosso("1", None, None).locacao


def test_rn_18_mondial_1003_e_faz_tudo_lar():
    assert ContextoEndosso("1", None, "1003").faz_tudo_lar
    assert not ContextoEndosso("1", None, "1002").faz_tudo_lar
    assert not ContextoEndosso("1", None, None).faz_tudo_lar


# ------------------------------------------------------------------ RN-20
def test_rn_20_cod_0800_com_abrev():
    c = _certificado_13008(
        chave=ChaveCertificado("adm", "15008", 0, 381066, "3082/01/AP 1302", "05554363733"),
        administradora=Administradora("adm", "X", "19PAEL"),
    )
    assert c.cod_0800 == "3082/01/AP 1302 19PAEL"
    assert c.administradora.avisos() == []


def test_rn_20_abrev_ausente_recompoe_sem_sufixo_e_avisa():
    c = _certificado_13008()
    assert c.cod_0800 == "CF1DI/AP.602"
    assert CodigoAviso.ABREV_ADM_AUSENTE in {a.codigo for a in c.todos_avisos()}


def test_rn_20_abrev_em_branco_conta_como_ausente():
    assert Administradora("a", "n", "   ").abreviacao_normalizada is None


# ------------------------------------------------------------------ ADR-05
def test_adr_05_matriz_de_templates_7_3():
    ruptura = CATALOGO.produto("0004")
    residencial = CATALOGO.produto("0001")
    m = Marca.PADRAO

    def ctx(loc, ft, prod):
        return ContextoTemplate(loc, ft, prod, exibe_premio=True, marca=m).nome

    assert ctx(False, False, ruptura) == "incendio"
    assert ctx(False, True, ruptura) == "incendio_ruptura_faz_tudo"
    assert ctx(False, True, residencial) == "incendio_faz_tudo_24h"
    assert ctx(True, False, ruptura) == "locacao_simples"
    assert ctx(True, True, residencial) == "locacao_faz_tudo"


def test_7_3_marca_alternativa_apenas_para_15008():
    assert marca_para_apolice("15008") is Marca.ALTERNATIVA
    assert marca_para_apolice("13008") is Marca.PADRAO


def test_adr_05_certificado_de_referencia_usa_incendio_ruptura_faz_tudo():
    ctx = _certificado_13008().contexto_template(exibe_premio=True)
    assert ctx.nome == "incendio_ruptura_faz_tudo"  # como em _meta.template da secao 9.1
    assert ctx.marca is Marca.PADRAO


# ---------------------------------------------------------------- avisos
def test_rd_23_todos_avisos_agrega_as_partes():
    codigos = {a.codigo for a in _certificado_13008().todos_avisos()}
    # referencia 13008: abrev nula (RN-20), portal nulo (GAP-11); o fixture nao resolve a
    # seguradora (cod "1" fora de seguradoras.toml), logo RN-28 tambem avisa
    assert codigos == {
        CodigoAviso.ABREV_ADM_AUSENTE,
        CodigoAviso.PORTAL_AUSENTE,
        CodigoAviso.LOGO_SEGURADORA_AUSENTE,
    }


def test_gap_11_portal_presente_nao_avisa():
    c = _certificado_13008(
        contrato=Contrato(
            "13008", 0, 380819, "380819", "1", "x", "y", codigo_pedido_porto=123, sucursal="RJ"
        )
    )
    assert CodigoAviso.PORTAL_AUSENTE not in {a.codigo for a in c.todos_avisos()}


# ------------------------------------------------------- GAP-13 fechado
def test_rn_25_susep_corretora_fixo_por_padrao():
    assert _certificado_13008().contrato.susep_corretora == "00000202049583"


def test_rn_23_plano_res_ou_com():
    assert plano_para_tipo_categoria("R") == "RES"
    assert plano_para_tipo_categoria("C") == "COM"
    assert plano_para_tipo_categoria("S") == "COM"
    assert plano_para_tipo_categoria(None) == "INC"
    assert plano_para_tipo_categoria(" ") == "INC"
    assert _certificado_13008().contrato.plano is None  # fixture sem tipo_categoria


def test_rn_18a_ruptura_deriva_faz_tudo_lar_e_operador_pode_desmarcar():
    c = _certificado_13008(
        endosso=ContextoEndosso(endosso="380819", cod_cat=None, codigo_assist_mondial="1002")
    )
    assert c.exibe_bloco_ruptura and c.faz_tudo_lar_derivado  # RN-18a
    assert c.faz_tudo_lar_efetivo() is True
    assert c.aviso_faz_tudo_lar(True) is None
    aviso = c.aviso_faz_tudo_lar(False)
    assert aviso is not None and aviso.codigo == CodigoAviso.FAZ_TUDO_LAR_MANUAL
    assert c.contexto_template(exibe_premio=False).nome == "incendio_ruptura_faz_tudo"


@pytest.mark.parametrize("ruim", [None, "", ".", "RK", "sp "])
def test_rn_26_sucursal_fora_de_uf_gera_aviso(ruim):
    c = _certificado_13008(
        contrato=Contrato("13008", 0, 380819, "380819", "1", "x", "y", None, sucursal=ruim)
    )
    assert CodigoAviso.SUCURSAL_INVALIDA in {a.codigo for a in c.todos_avisos()}


def test_rn_26_sucursal_rj_nao_gera_aviso():
    codigos = {a.codigo for a in _certificado_13008().todos_avisos()}
    assert CodigoAviso.SUCURSAL_INVALIDA not in codigos
