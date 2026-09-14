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
    AVISO_REEMISSAO,
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

    def listar_vigencias_portal(self, administradora, cpf_cnpj):
        """QRY-14 / RD-30 em memoria: mesma adm e doc, sem olhar vigencia (RN-35)."""
        self.verificacoes.append((administradora, cpf_cnpj))
        return [
            RepositorioFirebird._montar_vigencia(
                {**li, "cpf_cnpj": li["documento_seg"], "nome": li["beneficiario"]}
            )
            for li in self.linhas
            if li["administradora"] == administradora and li["documento_seg"] == cpf_cnpj
        ]

    def localizar_por_portal(
        self, administradora, cpf_cnpj, vigencia, fatura=None, certificado=None
    ):
        self.chamadas.append((administradora, cpf_cnpj, vigencia))
        return [
            self._m._montar(li)
            for li in self.linhas
            if li["administradora"] == administradora
            and li["documento_seg"] == cpf_cnpj
            and li["inicio_vig"] == vigencia
            and (fatura is None or li["fatura"] == fatura)
            and (certificado is None or li["certificado"] == certificado)
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


def test_rn_33_revista_segundo_pedido_reemite_e_sobrescreve(opcoes, tmp_path):
    # 14/09/2026: a API sempre reemite. Mesmos nomes de arquivo (sem ' (1)'), mesma chave
    # no S3, UPDATE de novo, aviso REEMISSAO quando ja havia link.
    pub, reg = PublicadorFalso(), RegistroFalso()
    primeira = emitir_para_portal(
        RepoFalso([LINHA_13008]), pub, reg, PEDIDO, opcoes, render_falso
    ).certificados[0]
    assert AVISO_REEMISSAO not in primeira.avisos
    antes = sorted(p.name for p in tmp_path.rglob("*") if p.is_file())

    linha = {**LINHA_13008, "link_certificado_aws": primeira.link}
    resp = emitir_para_portal(RepoFalso([linha]), pub, reg, PEDIDO, opcoes, render_falso)
    [item] = resp.certificados
    assert item.situacao == "publicado" and item.link == primeira.link
    assert AVISO_REEMISSAO in item.avisos
    assert item.documento["arquivo"]["link"] == item.link
    assert len(pub.publicados) == 2 and len(reg.registros) == 2  # publicou e gravou de novo
    assert sorted(p.name for p in tmp_path.rglob("*") if p.is_file()) == antes  # sem copias


def test_rn_33_revista_link_do_legado_e_substituido(opcoes, tmp_path):
    # Banco com 930 mil links do Delphi (sem JSON em disco): a API emite e troca o link.
    legado = "https://certincendioaws.s3.us-east-2.amazonaws.com/0000001192//072026/380819/0_x.pdf"
    linha = {**LINHA_13008, "link_certificado_aws": legado}
    pub, reg = PublicadorFalso(), RegistroFalso()
    resp = emitir_para_portal(RepoFalso([linha]), pub, reg, PEDIDO, opcoes, render_falso)
    [item] = resp.certificados
    assert item.situacao == "publicado" and item.link != legado and item.documento
    assert AVISO_REEMISSAO in item.avisos
    [(_, link_gravado, _)] = reg.registros
    assert link_gravado == item.link  # o UPDATE substituiu o link do legado
    assert list(tmp_path.rglob("*.json")) and list(tmp_path.rglob("*.pdf"))


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
    # 14/09/2026: chaves literais no Postman -> 13 caracteres numa CHAR(10); era 500 no driver
    with pytest.raises(PedidoInvalido, match="ate 10 caracteres"):
        PedidoVerificacao.criar("{0000000019}", "{05554363733}")
    with pytest.raises(PedidoInvalido, match="ate 10 caracteres"):
        PedidoPortal.criar("00000000019X", "05554363733", date(2026, 7, 1))


VERIF = PedidoVerificacao.criar("0000001192", "33016330725")


def _mes(linha, ano, mes, fatura, **extra):
    from calendar import monthrange

    return {
        **linha,
        "inicio_vig": date(ano, mes, 1),
        "final_vig": date(ano, mes, monthrange(ano, mes)[1]),
        "fatura": fatura,
        **extra,
    }


def test_rn_35_existe_sem_olhar_vigencia_e_devolve_rd_30():
    # 14/09/2026: vigencias sao mensais (uma por fatura) e a fatura do mes entra com
    # atraso; segurado com a ultima vigencia encerrada continua existindo para o portal.
    linha = {
        **LINHA_13008,
        "cod_produto": "0271",
        "nom_produto": "TOTAL PROTECAO",
        "des_prod": "TOTAL PROTECAO RESIDENCIAL / FAZ TUDO",
        "des_prod_master": "TOTAL CONTEUDO",
    }
    repo = RepoFalso([linha])  # vigencia 07/2026, ja encerrada
    resp = verificar_segurado(repo, VERIF)
    assert resp.existe is True
    assert repo.verificacoes == [("0000001192", "33016330725")]
    d = resp.para_dict()
    assert d["existe"] is True and d["quantidade"] == 1
    [c] = d["certificados"]
    assert c == {
        "nome": "JORGE EDUARDO MONT SERRAT",
        "endereco": {
            "logradouro": "AV LUCIO COSTA, 3300 BLOCO 2", "unidade": "AP.602",
            "bairro": "BARRA DA TIJUA", "cidade": "RIO DE JANEIRO", "uf": "RJ",
            "cep": "22630010", "condominio": "DIRETORIA IMODATA",
        },
        "inicio_vig": "2026-07-01", "final_vig": "2026-07-31",
        "apolice": "13008", "seq": 0, "fatura": 380819, "certificado": "CF1DI/AP.602",
        "produto": {
            "codigo": "0271", "nome": "TOTAL PROTECAO",
            "descricao_fatura": "TOTAL PROTECAO RESIDENCIAL / FAZ TUDO",
            "descricao_master": "TOTAL CONTEUDO",
        },
    }  # fmt: skip
    assert "cpf_cnpj" not in c  # o portal ja tem o documento; nao repete


def test_rn_35_nao_existe_e_lista_vazia():
    repo = RepoFalso([LINHA_13008])
    outra_adm = PedidoVerificacao.criar("0000000019", "33016330725")
    outro_doc = PedidoVerificacao.criar("0000001192", "05554363733")
    for pedido in (outra_adm, outro_doc):
        resp = verificar_segurado(repo, pedido)
        assert resp.existe is False
        assert resp.para_dict() == {"existe": False, "quantidade": 0, "certificados": []}


def test_rn_35a_tres_vigencias_mais_recentes_com_todas_as_unidades():
    # 5 meses; em 07/2026 ha duas unidades (RD-22). Devolve 07, 06 e 05 = 4 linhas.
    linhas = [
        _mes(LINHA_13008, 2026, 3, 379000),
        _mes(LINHA_13008, 2026, 4, 379500),
        _mes(LINHA_13008, 2026, 5, 380000),
        _mes(LINHA_13008, 2026, 6, 380400),
        _mes(LINHA_13008, 2026, 7, 380819),
        _mes(LINHA_13008, 2026, 7, 380819, certificado="CF1DI/AP.701", unidade="AP.701"),
    ]
    resp = verificar_segurado(RepoFalso(linhas), VERIF)
    got = [(v.inicio_vig.isoformat(), v.fatura, v.certificado) for v in resp.vigencias]
    assert got == [
        ("2026-07-01", 380819, "CF1DI/AP.602"),
        ("2026-07-01", 380819, "CF1DI/AP.701"),
        ("2026-06-01", 380400, "CF1DI/AP.602"),
        ("2026-05-01", 380000, "CF1DI/AP.602"),
    ]
    assert resp.para_dict()["quantidade"] == 4


def test_gap_25_fechado_final_vig_zero_delphi_nao_impede_e_sai_null():
    linha = {**LINHA_13008, "final_vig": date(1899, 12, 30)}  # DEF-06
    resp = verificar_segurado(RepoFalso([linha]), VERIF)
    assert resp.existe is True
    assert resp.para_dict()["certificados"][0]["final_vig"] is None


def test_rd_31_emitir_aponta_fatura_e_certificado(opcoes):
    # Duas unidades na mesma vigencia (RD-22): com certificado no pedido, emite so uma.
    repo = RepoFalso([LINHA_13008, LINHA_B])
    pedido = PedidoPortal.criar(
        "0000001192", "33016330725", date(2026, 7, 1), fatura=380819, certificado="CF1DI/AP.701"
    )
    assert pedido.para_dict()["fatura"] == 380819
    assert pedido.para_dict()["certificado"] == "CF1DI/AP.701"
    resp = emitir_para_portal(
        repo, PublicadorFalso(), RegistroFalso(), pedido, opcoes, render_falso
    )
    [item] = resp.certificados
    assert item.chave.certificado == "CF1DI/AP.701" and item.situacao == "publicado"
    # fatura errada: nada encontrado (404)
    errado = PedidoPortal.criar("0000001192", "33016330725", date(2026, 7, 1), fatura=1)
    with pytest.raises(NenhumCertificado, match="fatura 1"):
        emitir_para_portal(repo, PublicadorFalso(), RegistroFalso(), errado, opcoes, render_falso)
    with pytest.raises(PedidoInvalido):
        PedidoPortal.criar("0000001192", "33016330725", date(2026, 7, 1), fatura=-5)
