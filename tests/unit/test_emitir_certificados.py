"""RF-07 / RF-09 / RF-11 / RF-16 — caso de uso de emissao com repositorio falso (sem banco)."""

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from certgen.adapters.firebird.repositorio import RepositorioFirebird
from certgen.application.emitir_certificados import OpcoesEmissao, emitir_lote
from certgen.domain.certificado import ChaveLote
from certgen.domain.produto import ProdutoIndeterminado
from tests.unit.test_emitir_portal import PublicadorFalso, RegistroFalso, render_falso
from tests.unit.test_repositorio_mapeamento import LINHA_13008

BRT = timezone(timedelta(hours=-3))
AGORA = datetime(2026, 9, 3, 14, 22, 7, tzinfo=BRT)
LOTE = ChaveLote("0000001192", "13008", 1, 380819)

LINHA_B = {
    **LINHA_13008,
    "certificado": "CF1DI/AP.701",
    "documento_seg": "05554363733",
    "beneficiario": "OUTRA PESSOA",
    "abrev_adm": "IMO",
}


class RepoFalso:
    """Devolve certificados montados pelo mapeador real, a partir de linhas em memoria."""

    def __init__(self, linhas, erro=None):
        self._linhas = linhas
        self._erro = erro
        self._mapeador = RepositorioFirebird()

    def listar_segurados(self, lote):
        if self._erro:
            raise self._erro
        return [self._mapeador._montar(dict(linha, seq=lote.seq)) for linha in self._linhas]


@pytest.fixture
def opcoes(tmp_path):
    return OpcoesEmissao(pasta_saida=tmp_path, agora=lambda: AGORA)


def test_uc_01_emite_json_de_todos_os_segurados_do_lote(opcoes, tmp_path):
    rel = emitir_lote(RepoFalso([LINHA_13008, LINHA_B]), LOTE, opcoes)
    assert not rel.falhas
    nomes = sorted(e.json_path.name for e in rel.emitidos)
    assert nomes == [
        "0_05554363733_0004_13008_CF1DI-AP701_380819.json",
        "0_33016330725_0004_13008_CF1DI-AP602_380819.json",
    ]
    # RN-19: pasta {adm}/{competencia} a partir do inicio_vig 2026-07-01
    assert all(e.json_path.parent == tmp_path / "0000001192" / "072026" for e in rel.emitidos)


def test_rd_25_json_gravado_aponta_para_o_pdf_e_a_pasta(opcoes):
    rel = emitir_lote(RepoFalso([LINHA_13008]), LOTE, opcoes)
    doc = json.loads(rel.emitidos[0].json_path.read_text(encoding="utf-8"))
    assert doc["arquivo"]["pdf"] == "0_33016330725_0004_13008_CF1DI-AP602_380819.pdf"
    assert doc["arquivo"]["pasta_destino"] == "0000001192/072026"
    assert doc["arquivo"]["link"] is None
    assert doc["_origem"]["chave"]["seq"] == 1


def test_rn_19_competencia_informada_prevalece(tmp_path):
    op = OpcoesEmissao(pasta_saida=tmp_path, agora=lambda: AGORA, data_competencia=date(2026, 9, 1))
    rel = emitir_lote(RepoFalso([LINHA_13008]), LOTE, op)
    assert rel.emitidos[0].json_path.parent.name == "092026"


def test_rf_09_falha_em_um_nao_interrompe_o_lote(opcoes):
    ruim = {**LINHA_13008, "certificado": "A:B", "documento_seg": "11111111111"}  # RN-17b
    rel = emitir_lote(RepoFalso([ruim, LINHA_13008]), LOTE, opcoes)
    assert len(rel.emitidos) == 1
    assert len(rel.falhas) == 1
    assert rel.falhas[0].tipo == "NomeArquivoInvalido"
    assert rel.falhas[0].chave.certificado == "A:B"


def test_rn_03_3_apolice_sem_produto_falha_o_lote_inteiro(opcoes):
    erro = ProdutoIndeterminado("99999")
    rel = emitir_lote(RepoFalso([], erro=erro), LOTE, opcoes)
    assert rel.emitidos == []
    assert rel.falhas[0].tipo == "ProdutoIndeterminado"
    assert "99999" in rel.falhas[0].motivo


def test_uc_02_selecao_parcial(opcoes):
    todos = emitir_lote(RepoFalso([LINHA_13008, LINHA_B]), LOTE, opcoes)
    alvo = todos.emitidos[1].chave
    op2 = OpcoesEmissao(pasta_saida=opcoes.pasta_saida / "sel", agora=lambda: AGORA, apenas=[alvo])
    rel = emitir_lote(RepoFalso([LINHA_13008, LINHA_B]), LOTE, op2)
    assert [e.chave for e in rel.emitidos] == [alvo]


def test_rn_13_reemissao_nao_sobrescreve(opcoes):
    emitir_lote(RepoFalso([LINHA_13008]), LOTE, opcoes)
    rel = emitir_lote(RepoFalso([LINHA_13008]), LOTE, opcoes)
    assert rel.emitidos[0].colisao is True
    assert rel.emitidos[0].json_path.name.endswith(" (1).json")


def test_rf_16_pdf_so_e_renderizado_depois_do_json_valido(opcoes):
    chamadas = []

    def render(cert, meta, destino):
        assert (destino.parent / meta.nome_pdf.replace(".pdf", ".json")).exists()
        chamadas.append(destino)
        destino.write_bytes(b"%PDF-fake")
        return destino

    rel = emitir_lote(RepoFalso([LINHA_13008]), LOTE, opcoes, renderizar_pdf=render)
    assert rel.emitidos[0].pdf_path == chamadas[0]
    assert chamadas[0].name == "0_33016330725_0004_13008_CF1DI-AP602_380819.pdf"


def test_rd_23_relatorio_lista_avisos(opcoes):
    rel = emitir_lote(RepoFalso([LINHA_13008]), LOTE, opcoes)
    assert set(rel.emitidos[0].avisos) == {"ABREV_ADM_AUSENTE", "PORTAL_AUSENTE"}
    texto = rel.resumo()
    assert "1 emitidos, 0 falhas" in texto
    assert "ABREV_ADM_AUSENTE" in texto


# ---------------------------------------------------------------- RF-21 Upload AWS
def test_rf_21_upload_publica_registra_e_regrava_o_json_com_o_link(opcoes):
    pub, reg = PublicadorFalso(), RegistroFalso()
    rel = emitir_lote(
        RepoFalso([LINHA_13008, LINHA_B]), LOTE, opcoes, render_falso, publicador=pub, registro=reg
    )
    assert rel.falhas == [] and len(rel.emitidos) == 2
    for e in rel.emitidos:
        assert e.link and e.link.startswith("https://certincendioaws.s3.us-east-2.amazonaws.com/")
        assert e.link.endswith(e.pdf_path.name)  # RN-29: o nome do PDF fecha o caminho
        doc = json.loads(e.json_path.read_text(encoding="utf-8"))
        assert doc["arquivo"]["link"] == e.link  # RD-25 regravado apos upload
    assert pub.publicados[0].startswith("0000001192/0004/072026/380819/")  # RN-29
    assert [r[0] for r in reg.registros] == [e.chave for e in rel.emitidos]  # RD-20a
    d = rel.para_dict()
    assert d["emitidos"][0]["link"] == rel.emitidos[0].link
    assert rel.emitidos[0].link in rel.resumo()


def test_rf_21_falha_no_s3_vira_falha_do_certificado_sem_gravar_link(opcoes):
    reg = RegistroFalso()
    rel = emitir_lote(
        RepoFalso([LINHA_13008]), LOTE, opcoes, render_falso,
        publicador=PublicadorFalso(falhar=True), registro=reg,
    )  # fmt: skip
    assert rel.emitidos == [] and len(rel.falhas) == 1
    assert rel.falhas[0].tipo == "ErroPublicacao"
    assert reg.registros == []  # RF-16: nada gravado sem upload confirmado


def test_rf_21_update_que_falha_nao_devolve_link(opcoes):
    pub = PublicadorFalso()
    rel = emitir_lote(
        RepoFalso([LINHA_13008]), LOTE, opcoes, render_falso,
        publicador=pub, registro=RegistroFalso(falhar=True),
    )  # fmt: skip
    assert rel.emitidos == [] and rel.falhas[0].tipo == "LinkNaoRegistrado"
    assert len(pub.publicados) == 1  # o objeto ficou no bucket; o motivo e explicito


def test_rf_21_reemissao_com_link_anterior_gera_aviso(opcoes):
    linha = {**LINHA_13008, "link_certificado_aws": "https://antigo/x.pdf"}  # RD-28
    rel = emitir_lote(
        RepoFalso([linha]), LOTE, opcoes, render_falso,
        publicador=PublicadorFalso(), registro=RegistroFalso(),
    )  # fmt: skip
    assert "REEMISSAO" in rel.emitidos[0].avisos


def test_rf_21_json_unico_recebe_o_link_de_cada_certificado(tmp_path):
    opcoes = OpcoesEmissao(pasta_saida=tmp_path, agora=lambda: AGORA, json_unico=True)
    rel = emitir_lote(
        RepoFalso([LINHA_13008, LINHA_B]), LOTE, opcoes, render_falso,
        publicador=PublicadorFalso(), registro=RegistroFalso(),
    )  # fmt: skip
    doc = json.loads(rel.json_unico.read_text(encoding="utf-8"))
    links = {v["arquivo"]["link"] for v in doc["certificados"].values()}
    assert links == {e.link for e in rel.emitidos} and None not in links


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(renderizar_pdf=None),  # sem PDF nao ha o que publicar
        dict(publicador=None),  # publicador e registro andam juntos
    ],
)
def test_rf_21_combinacoes_invalidas_sao_recusadas_antes_de_emitir(opcoes, tmp_path, kwargs):
    base = dict(renderizar_pdf=render_falso, publicador=PublicadorFalso(), registro=RegistroFalso())
    with pytest.raises(ValueError, match="RF-21"):
        emitir_lote(RepoFalso([LINHA_13008]), LOTE, opcoes, **{**base, **kwargs})
    assert not any(tmp_path.iterdir())  # RF-16: nada foi gravado


def test_rf_21_upload_exige_modo_individuais(tmp_path):
    opcoes = OpcoesEmissao(pasta_saida=tmp_path, agora=lambda: AGORA, individuais=False)
    with pytest.raises(ValueError, match="Individuais"):
        emitir_lote(
            RepoFalso([LINHA_13008]), LOTE, opcoes, render_falso,
            publicador=PublicadorFalso(), registro=RegistroFalso(),
        )  # fmt: skip
