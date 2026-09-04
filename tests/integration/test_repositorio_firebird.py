"""Integracao com o FATURA.GDB real (somente SELECT). Pula se nao houver .env/conexao.

Aceitacao da Fase 1: dada uma chave real, obter_certificado() devolve Certificado
tipado e completo; RN-03.3 falha para apolice desconhecida; RD-23 popula avisos.
"""

from __future__ import annotations

import pytest

from certgen.adapters.firebird import conexao
from certgen.adapters.firebird.repositorio import RepositorioFirebird
from certgen.application.ports import CertificadoNaoEncontrado
from certgen.config.settings import ConfiguracaoAusente
from certgen.domain.avisos import CodigoAviso
from certgen.domain.certificado import ChaveCertificado, ChaveLote

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def repo() -> RepositorioFirebird:
    try:
        conexao.verificar_conexao()
    except (ConfiguracaoAusente, conexao.ErroConexao) as exc:
        pytest.skip(f"Firebird indisponivel: {exc}")
    yield RepositorioFirebird()
    conexao.esvaziar_pools()


def test_qry_01_administradoras_ativas_incluem_imodata(repo):
    adms = repo.listar_administradoras()
    por_codigo = {a.codigo: a for a in adms}
    assert "0000001192" in por_codigo
    assert por_codigo["0000001192"].nome.startswith("IMODATA")
    assert por_codigo["0000001192"].abreviacao is None  # RN-20: abrev vazia -> ausente
    assert "0000004691" not in por_codigo  # status 'C', RD-03
    # A ordem por nome e do ORDER BY (colacao do banco); nao se compara com sorted() do Python.


def test_qry_03_qry_04_cascata_da_referencia_13008(repo):
    apolices = repo.listar_apolices("0000001192", inicio_vig=None)
    seqs = [a.seq for a in apolices if a.apolice == "13008"]
    assert seqs, "administradora 0000004691 deveria ter a apolice 13008"
    faturas = {f for seq in seqs for f in repo.listar_faturas("0000001192", "13008", seq, None)}
    assert 380819 in faturas


def test_rn_05a_data_fat_filtra_faturas_e_apolices(repo):
    from datetime import date

    # fatura 380819: data_fat = 2026-07-30, dt_ini_vig = 2026-07-01 (verificado em 04/09/2026)
    com = repo.listar_faturas("0000001192", "13008", 1, None, data_fat=date(2026, 7, 30))
    assert com == [380819]
    assert repo.listar_faturas("0000001192", "13008", 1, None, data_fat=date(2026, 7, 29)) == []
    assert repo.listar_apolices("0000001192", None, data_fat=date(2026, 7, 30))
    assert repo.listar_apolices("0000001192", None, data_fat=date(1999, 1, 1)) == []


def test_rf_15_administradora_vazia_nao_lista_apolices(repo):
    with pytest.raises(ValueError):
        repo.listar_apolices("", None)


def _lote_referencia(repo, administradora: str, apolice: str, fatura: int) -> ChaveLote:
    for a in repo.listar_apolices(administradora, None):
        if a.apolice != apolice:
            continue
        if fatura in repo.listar_faturas(administradora, apolice, a.seq, None):
            return ChaveLote(administradora, apolice, a.seq, fatura)
    pytest.fail(f"lote {administradora}/{apolice}/{fatura} nao encontrado")


def test_rd_24_listar_segurados_e_obter_certificado_devolvem_o_mesmo_objeto(repo):
    lote = _lote_referencia(repo, "0000001192", "13008", 380819)
    segurados = repo.listar_segurados(lote)
    assert segurados
    alvo = next(c for c in segurados if c.chave.certificado == "CF1DI/AP.602")
    assert alvo.chave.cpf_cnpj == "33016330725"
    assert repo.obter_certificado(alvo.chave) == alvo


def test_fase_1_referencia_13008_completa(repo):
    lote = _lote_referencia(repo, "0000001192", "13008", 380819)
    c = next(x for x in repo.listar_segurados(lote) if x.chave.certificado == "CF1DI/AP.602")
    assert c.produto.codigo == "0004"
    assert c.segurado_nome.startswith("JORGE EDUARDO")
    assert c.endosso.faz_tudo_lar is True
    assert c.contrato.sucursal == "RJ"  # RN-26 — SUC. do PDF de referencia
    assert c.contexto_template(True).nome == "incendio_ruptura_faz_tudo"
    assert len(c.coberturas) == 11
    codigos = {a.codigo for a in c.todos_avisos()}
    assert CodigoAviso.ABREV_ADM_AUSENTE in codigos  # RN-20: IMODATA sem abrev
    assert CodigoAviso.PORTAL_AUSENTE in codigos


def test_rn_03_1_referencia_15008_administradora_19(repo):
    lote = _lote_referencia(repo, "0000000019", "15008", 381066)
    pares = {c.chave.certificado: c for c in repo.listar_segurados(lote)}
    assert {"3082/01/AP 1302", "3082/01/AP 1101"} <= set(pares)
    c = pares["3082/01/AP 1302"]
    assert c.chave.cpf_cnpj == "05554363733"
    assert c.produto.codigo == "0001"  # RN-03.1, nao 0004
    codigos = {a.codigo for a in c.todos_avisos()}
    assert CodigoAviso.PRODUTO_POR_EXCECAO in codigos
    assert CodigoAviso.FINAL_VIG_AUSENTE in codigos  # DEF-06
    assert c.vigencia.fim is None


def test_rd_09_chave_inexistente_nao_encontrado(repo):
    chave = ChaveCertificado("0000001192", "13008", 1, 380819, "NAO-EXISTE", "00000000000")
    with pytest.raises(CertificadoNaoEncontrado):
        repo.obter_certificado(chave)


def test_qry_11_contexto_endosso_da_fatura_380819(repo):
    ctx = repo.obter_contexto_endosso(380819)
    assert ctx.endosso is not None
    assert ctx.faz_tudo_lar is True
