"""UC-12 — emissao a pedido do portal com adaptadores falsos (sem banco, sem S3, sem Chromium).

Cobre RD-27, RN-31..RN-34, RF-16 (ordem e abort por certificado), RF-09, RN-29.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from certgen.adapters.firebird.repositorio import RepositorioFirebird
from certgen.application.emitir_certificados import OpcoesEmissao
from certgen.application.emitir_portal import (
    NenhumCertificado,
    PedidoInvalido,
    PedidoPortal,
    PedidoVerificacao,
    emitir_para_portal,
    verificar_segurado,
)
from certgen.application.ports import ErroPublicacao, LinkNaoRegistrado
from certgen.domain.nomes_arquivo import caminho_publicacao
from tests.unit.test_repositorio_mapeamento import LINHA_13008

BRT = timezone(timedelta(hours=-3))
AGORA = datetime(2026, 9, 10, 10, 0, 0, tzinfo=BRT)
PEDIDO = PedidoPortal.criar("0000001192", "330.163.307-25", date(2026, 7, 1))

LINHA_B = {  # RD-22: mesmo CPF, outra unidade
    **LINHA_13008,
    "certificado": "CF1DI/AP.701",
    "unidade": "AP.701",
}


class RepoFalso:
    def __init__(self, linhas):
        self.linhas = linhas
        self.chamadas = []
        self.verificacoes = []
        self._m = RepositorioFirebird()

    def existe_segurado(self, administradora, cpf_cnpj, hoje):
        """QRY-14 / RN-35 em memoria: nao cancelado, mesma adm e doc, vigencia inclui hoje."""
        self.verificacoes.append((administradora, cpf_cnpj, hoje))
        return any(
            li["administradora"] == administradora
            and li["documento_seg"] == cpf_cnpj
            and li["inicio_vig"] <= hoje <= li["final_vig"]
            for li in self.linhas
        )

    def localizar_por_portal(self, administradora, cpf_cnpj, vigencia):
        self.chamadas.append((administradora, cpf_cnpj, vigencia))
        return [
            self._m._montar(li)
            for li in self.linhas
            if li["administradora"] == administradora
            and li["documento_seg"] == cpf_cnpj
            and li["inicio_vig"] == vigencia
        ]


class PublicadorFalso:
    def __init__(self, falhar=False):
        self.publicados = []
        self.falhar = falhar

    def publicar(self, arquivo: Path, destino: str) -> str:
        assert arquivo.is_file() and arquivo.stat().st_size > 0
        if self.falhar:
            raise ErroPublicacao("S3 fora")
        self.publicados.append(destino)
        return f"https://certincendioaws.s3.us-east-2.amazonaws.com/{destino}"


class RegistroFalso:
    def __init__(self, falhar=False):
        self.registros = []
        self.falhar = falhar

    def registrar_link(self, chave, link, quando):
        if self.falhar:
            raise LinkNaoRegistrado(chave, 0)
        self.registros.append((chave, link, quando))


def render_falso(cert, meta, destino: Path) -> Path:
    destino.write_bytes(b"%PDF-1.4 falso\n")
    return destino


@pytest.fixture
def opcoes(tmp_path):
    return OpcoesEmissao(pasta_saida=tmp_path, agora=lambda: AGORA)


def test_rf_18_pedido_normaliza_cpf_e_valida():
    assert PEDIDO.cpf_cnpj == "33016330725"
    with pytest.raises(PedidoInvalido):
        PedidoPortal.criar("0000001192", "123", date(2026, 7, 1))
    with pytest.raises(PedidoInvalido):
        PedidoPortal.criar("", "33016330725", date(2026, 7, 1))


def test_uc_12_publica_registra_e_devolve_link(opcoes, tmp_path):
    repo, pub, reg = RepoFalso([LINHA_13008]), PublicadorFalso(), RegistroFalso()
    resp = emitir_para_portal(repo, pub, reg, PEDIDO, opcoes, render_falso)

    assert repo.chamadas == [("0000001192", "33016330725", date(2026, 7, 1))]  # RN-31 exato
    [item] = resp.certificados
    assert item.situacao == "publicado"
    # RN-29: {adm}/{produto}/{competencia}/{fatura}/{pdf}
    esperado = "0000001192/0004/072026/380819/0_33016330725_0004_13008_CF1DI-AP602_380819.pdf"
    assert pub.publicados == [esperado]
    assert item.link.endswith(esperado)
    # RF-16: link gravado depois do upload, com a chave completa RD-01
    [(chave, link, quando)] = reg.registros
    assert chave == item.chave and link == item.link and quando == AGORA
    # RN-34 / RD-25: copia local com o JSON regravado apontando para o link
    js = tmp_path / "0000001192" / "072026" / "0_33016330725_0004_13008_CF1DI-AP602_380819.json"
    gravado = json.loads(js.read_text(encoding="utf-8"))
    assert gravado["arquivo"]["link"] == item.link
    assert js.with_suffix(".pdf").exists()
    assert resp.para_dict()["quantidade"] == 1
    # RD-29: o documento da resposta e o mesmo JSON gravado em disco (RNF-08)
    assert item.documento == gravado
    assert resp.para_dict()["certificados"][0]["documento"]["arquivo"]["link"] == item.link


def test_rd_27_sem_linhas_e_404(opcoes):
    with pytest.raises(NenhumCertificado):
        emitir_para_portal(
            RepoFalso([]), PublicadorFalso(), RegistroFalso(), PEDIDO, opcoes, render_falso
        )


def test_rn_32_varios_certificados_emite_todos(opcoes):
    pub = PublicadorFalso()
    resp = emitir_para_portal(
        RepoFalso([LINHA_13008, LINHA_B]), pub, RegistroFalso(), PEDIDO, opcoes, render_falso
    )
    assert [i.situacao for i in resp.certificados] == ["publicado", "publicado"]
    assert len({i.link for i in resp.certificados}) == 2
    assert len(pub.publicados) == 2


def test_rn_33_ja_publicado_devolve_link_e_documento_do_disco_sem_reemitir(opcoes, tmp_path):
    # 1a emissao grava o JSON; depois simula o banco ja com o link
    pub, reg = PublicadorFalso(), RegistroFalso()
    primeira = emitir_para_portal(
        RepoFalso([LINHA_13008]), pub, reg, PEDIDO, opcoes, render_falso
    ).certificados[0]
    antes = sorted(p.name for p in tmp_path.rglob("*") if p.is_file())

    linha = {**LINHA_13008, "link_certificado_aws": primeira.link}
    resp = emitir_para_portal(RepoFalso([linha]), pub, reg, PEDIDO, opcoes, render_falso)
    [item] = resp.certificados
    assert item.situacao == "ja_publicado" and item.link == primeira.link
    assert item.documento == primeira.documento  # RD-29: relido do disco
    assert len(pub.publicados) == 1 and len(reg.registros) == 1  # nada novo
    assert sorted(p.name for p in tmp_path.rglob("*") if p.is_file()) == antes


def test_rn_33_rd_29_ja_publicado_sem_json_no_disco_e_falha(opcoes, tmp_path):
    linha = {**LINHA_13008, "link_certificado_aws": "https://x/ja.pdf"}
    pub, reg = PublicadorFalso(), RegistroFalso()
    resp = emitir_para_portal(RepoFalso([linha]), pub, reg, PEDIDO, opcoes, render_falso)
    [item] = resp.certificados
    assert item.situacao == "falha" and item.link is None and item.documento is None
    assert "DocumentoAusente" in item.motivo and "https://x/ja.pdf" in item.motivo
    assert pub.publicados == [] and reg.registros == []
    assert not list(tmp_path.rglob("*"))  # nada gravado
    assert not resp.algum_link  # -> 502 na API


def test_rf_16_falha_no_s3_nao_grava_link(opcoes):
    reg = RegistroFalso()
    resp = emitir_para_portal(
        RepoFalso([LINHA_13008]), PublicadorFalso(falhar=True), reg, PEDIDO, opcoes, render_falso
    )
    [item] = resp.certificados
    assert item.situacao == "falha" and item.link is None
    assert "ErroPublicacao" in item.motivo
    assert reg.registros == []
    assert not resp.algum_link  # -> 502 na API


def test_rd_20a_update_falhou_nao_devolve_link(opcoes, tmp_path):
    resp = emitir_para_portal(
        RepoFalso([LINHA_13008]), PublicadorFalso(), RegistroFalso(falhar=True),
        PEDIDO, opcoes, render_falso,
    )  # fmt: skip
    [item] = resp.certificados
    assert item.situacao == "falha" and item.link is None
    assert "LinkNaoRegistrado" in item.motivo
    js = next(tmp_path.rglob("*.json"))
    assert json.loads(js.read_text(encoding="utf-8"))["arquivo"]["link"] is None


def test_rf_09_falha_em_um_nao_impede_o_outro(opcoes):
    class PubParcial(PublicadorFalso):
        def publicar(self, arquivo, destino):
            if "AP701" in destino:
                raise ErroPublicacao("so este falha")
            return super().publicar(arquivo, destino)

    resp = emitir_para_portal(
        RepoFalso([LINHA_13008, LINHA_B]), PubParcial(), RegistroFalso(), PEDIDO, opcoes,
        render_falso,
    )  # fmt: skip
    assert sorted(i.situacao for i in resp.certificados) == ["falha", "publicado"]
    assert resp.algum_link  # -> 200 na API


def test_rn_29_caminho_publicacao():
    assert (
        caminho_publicacao("0000001192", "0004", date(2026, 7, 1), 380819, "a.pdf")
        == "0000001192/0004/072026/380819/a.pdf"
    )


# ------------------------------------------------------------------ UC-13 / RF-20 / RN-35
def test_rf_20_pedido_verificacao_normaliza_e_valida():
    v = PedidoVerificacao.criar(" 0000001192 ", "330.163.307-25")
    assert v.para_dict() == {"administradora": "0000001192", "cpf_cnpj": "33016330725"}
    with pytest.raises(PedidoInvalido):
        PedidoVerificacao.criar("0000001192", "1234")
    with pytest.raises(PedidoInvalido):
        PedidoVerificacao.criar("", "33016330725")


def test_rn_35_existe_so_com_vigencia_ativa_hoje():
    repo = RepoFalso([LINHA_13008])  # inicio 2026-07-01, final 2026-07-31
    v = PedidoVerificacao.criar("0000001192", "33016330725")
    assert verificar_segurado(repo, v, date(2026, 7, 15)) is True
    assert verificar_segurado(repo, v, date(2026, 7, 1)) is True  # inclusivo
    assert verificar_segurado(repo, v, date(2026, 7, 31)) is True  # inclusivo
    assert verificar_segurado(repo, v, date(2026, 8, 1)) is False  # encerrada
    assert verificar_segurado(repo, v, date(2026, 6, 30)) is False  # ainda nao comecou
    assert repo.verificacoes[0] == ("0000001192", "33016330725", date(2026, 7, 15))


def test_rn_35_outra_administradora_ou_outro_documento_nao_existe():
    repo = RepoFalso([LINHA_13008])
    hoje = date(2026, 7, 15)
    outra_adm = PedidoVerificacao.criar("0000000019", "33016330725")
    outro_doc = PedidoVerificacao.criar("0000001192", "05554363733")
    assert verificar_segurado(repo, outra_adm, hoje) is False
    assert verificar_segurado(repo, outro_doc, hoje) is False


def test_gap_25_final_vig_zero_delphi_nao_autentica():
    linha = {**LINHA_13008, "final_vig": date(1899, 12, 30)}  # DEF-06
    v = PedidoVerificacao.criar("0000001192", "33016330725")
    assert verificar_segurado(RepoFalso([linha]), v, date(2026, 7, 15)) is False
