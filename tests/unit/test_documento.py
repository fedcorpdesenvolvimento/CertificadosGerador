"""RD-12 — tipo do documento pelo comprimento; RN-14 — mascaras."""

from certgen.domain.avisos import CodigoAviso
from certgen.domain.documento import Documento, TipoDocumento, somente_digitos


def test_rd_12_onze_digitos_e_cpf():
    doc = Documento.de("33016330725")
    assert doc.tipo is TipoDocumento.CPF
    assert doc.numero == "33016330725"
    assert doc.avisos() == []


def test_rd_12_catorze_digitos_e_cnpj():
    doc = Documento.de("12.345.678/0001-95")
    assert doc.tipo is TipoDocumento.CNPJ
    assert doc.numero == "12345678000195"


def test_rd_12_outro_comprimento_e_indefinido_com_aviso():
    doc = Documento.de("12345")
    assert doc.tipo is TipoDocumento.INDEFINIDO
    avisos = doc.avisos()
    assert len(avisos) == 1
    assert avisos[0].codigo is CodigoAviso.DOCUMENTO_INDEFINIDO


def test_def_08_cpf_com_e_sem_mascara_dao_o_mesmo_documento():
    # Os dois templates do legado gravavam o mesmo dado de formas diferentes.
    sem = Documento.de("05554363733")
    com = Documento.de("055.543.637-33")
    assert sem.numero == com.numero == "05554363733"
    assert sem.formatado == com.formatado


def test_rn_14_mascara_cpf():
    assert Documento.de("33016330725").formatado == "330.163.307-25"


def test_rn_14_mascara_cnpj():
    assert Documento.de("12345678000195").formatado == "12.345.678/0001-95"


def test_rd_13_original_preservado_para_auditoria():
    doc = Documento.de("055.543.637-33")
    assert doc.original == "055.543.637-33"


def test_somente_digitos_trata_none():
    assert somente_digitos(None) == ""
