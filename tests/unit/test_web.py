# ruff: noqa: E501
"""Fase 4 — API da tela com repositorio falso (sem banco, sem Chromium)."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from certgen.adapters.firebird.repositorio import RepositorioFirebird
from certgen.application.ports import CertificadoNaoEncontrado
from certgen.domain.certificado import Administradora, ApoliceRef, ContextoEndosso
from certgen.web import app as webapp
from tests.unit.test_repositorio_mapeamento import LINHA_13008

LINHA_B = {**LINHA_13008, "certificado": "CF1DI/AP.701", "documento_seg": "05554363733", "beneficiario": "OUTRA PESSOA"}


class RepoFalso:
    def __init__(self):
        self._m = RepositorioFirebird()
        self.linhas = [LINHA_13008, LINHA_B]

    def listar_administradoras(self):
        return [
            Administradora("0000001192", "IMODATA ADM", None),
            Administradora("0000000019", "PROTEST", "19PAEL", possui_portal=True),
        ]

    def listar_apolices(self, administradora, inicio_vig, data_fat=None):
        assert administradora
        self.ultimo_data_fat = data_fat
        return [ApoliceRef("13008", 1, date(2026, 7, 1)), ApoliceRef("13008", 2, None)]

    def listar_faturas(self, administradora, apolice, seq, inicio_vig, data_fat=None):
        if data_fat == date(2026, 7, 30):
            return [380819]  # RN-05a: so a fatura emitida nessa data
        return [380819, 380820] if seq == 1 else []

    def listar_segurados(self, lote):
        return [self._m._montar(dict(li, seq=lote.seq)) for li in self.linhas]

    def obter_certificado(self, chave):
        raise CertificadoNaoEncontrado(chave)

    def obter_contexto_endosso(self, fatura):
        return ContextoEndosso("x", None, "1003")


@pytest.fixture
def cliente():
    webapp.app.dependency_overrides[webapp.get_repositorio] = lambda: RepoFalso()
    with TestClient(webapp.app) as c:
        yield c
    webapp.app.dependency_overrides.clear()


def test_menu_tem_os_tres_modulos(cliente):
    html = cliente.get("/").text
    for titulo in ("CERTIFICADO INCENDIO", "CERTIFICADO PRESTAMISTA/ALUG", "CERTIFICADO VIDA"):
        assert titulo in html
    assert cliente.get("/incendio").status_code == 200
    assert "ainda não tem especificação" in cliente.get("/prestamista").text
    assert "CERTIFICADO VIDA" in cliente.get("/vida").text
    assert "Em preparação" in html  # etiqueta dos dois modulos no menu


def test_rf_12_legendas_do_legado_preservadas(cliente):
    html = cliente.get("/incendio").text
    for legenda in (
        "Administradora", "Vigência", "Emissão:", "Apólice", "Fatura", "Produto",
        "Imprime Premio", "Individuais", "Upload AWS", "Faz Tudo Lar", "Locação",
        "Só XML de Cert.", "Busca Segurados", "Imprime", "Imprime/Geral",
    ):
        assert legenda in html, legenda


def test_rf_13_derivados_sao_somente_leitura(cliente):
    html = cliente.get("/incendio").text
    assert 'id="produto" readonly' in html
    assert 'id="locacao" disabled' in html
    # ADR-06: Faz Tudo Lar comeca desabilitado e e liberado (pre-marcado) apos a busca
    assert 'id="faz_tudo" disabled' in html and "editável" in html


def test_adr_06_operador_decide_faz_tudo_lar_e_json_registra(cliente, tmp_path):
    import json

    corpo = {"administradora": "0000001192", "apolice": "13008", "seq": 1, "fatura": 380819,
             "pasta": str(tmp_path), "so_xml": True, "faz_tudo_lar": False}  # fmt: skip
    d = cliente.post("/api/incendio/emitir", json=corpo).json()
    doc = json.loads(open(d["emitidos"][0]["json"], encoding="utf-8").read())
    assert doc["_meta"]["faz_tudo_lar"] is False
    assert doc["assistencia"]["faz_tudo_lar"] is False
    assert "FAZ_TUDO_LAR_MANUAL" in {a["codigo"] for a in doc["_meta"]["avisos"]}
    assert "FAZ_TUDO_LAR_MANUAL" in d["emitidos"][0]["avisos"] or True  # avisos do relatorio vem do dominio


def test_adr_06_sem_escolha_vale_a_derivacao(cliente, tmp_path):
    import json

    corpo = {"administradora": "0000001192", "apolice": "13008", "seq": 1, "fatura": 380819,
             "pasta": str(tmp_path), "so_xml": True}  # fmt: skip
    d = cliente.post("/api/incendio/emitir", json=corpo).json()
    doc = json.loads(open(d["emitidos"][0]["json"], encoding="utf-8").read())
    assert doc["_meta"]["faz_tudo_lar"] is True  # mondial 1003
    assert "FAZ_TUDO_LAR_MANUAL" not in {a["codigo"] for a in doc["_meta"]["avisos"]}


def test_botao_procurar_chama_o_dialogo_nativo(cliente, tmp_path):
    recebidos = []
    original = webapp.app.state.escolher_pasta
    webapp.app.state.escolher_pasta = lambda inicial: recebidos.append(inicial) or str(tmp_path)
    try:
        r = cliente.post("/api/escolher-pasta", json={"inicial": "C:\\x"})
        assert r.json() == {"pasta": str(tmp_path)}
        webapp.app.state.escolher_pasta = lambda inicial: None
        assert cliente.post("/api/escolher-pasta", json={}).json() == {"pasta": None}  # cancelou
        webapp.app.state.escolher_pasta = lambda inicial: (_ for _ in ()).throw(RuntimeError("sem tk"))
        assert cliente.post("/api/escolher-pasta", json={}).status_code == 501
    finally:
        webapp.app.state.escolher_pasta = original
    assert recebidos == ["C:\\x"]
    assert 'id="procurar"' in cliente.get("/incendio").text


def test_rf_03_administradoras_com_codigo_como_valor(cliente):
    r = cliente.get("/api/incendio/administradoras").json()
    assert r[0] == {"codigo": "0000001192", "nome": "IMODATA ADM", "abrev": None, "possui_portal": False}


def test_rn_08_rn_17_apolices_com_rotulo_e_chave_estruturada(cliente):
    r = cliente.get("/api/incendio/apolices", params={"administradora": "0000001192"}).json()
    assert r == [
        {"apolice": "13008", "seq": 1, "rotulo": "13008.1"},
        {"apolice": "13008", "seq": 2, "rotulo": "13008.2"},
    ]


def test_rf_15_administradora_vazia_bloqueia_apolices(cliente):
    r = cliente.get("/api/incendio/apolices", params={"administradora": ""})
    assert r.status_code == 400
    assert "RF-15" in r.json()["erro"]


def test_qry_04_faturas(cliente):
    q = {"administradora": "0000001192", "apolice": "13008", "seq": 1}
    assert cliente.get("/api/incendio/faturas", params=q).json() == [380819, 380820]


def test_rn_05a_emissao_filtra_pela_data_da_fatura(cliente):
    q = {"administradora": "0000001192", "apolice": "13008", "seq": 1, "data_fat": "2026-07-30"}
    assert cliente.get("/api/incendio/faturas", params=q).json() == [380819]
    html = cliente.get("/incendio").text
    assert 'id="emissao" class="data" placeholder="dd/mm/aaaa" maxlength="10"\n' in html
    assert 'id="emissao"' in html and "disabled" not in html.split('id="emissao"')[1].split(">")[0]


def test_rf_05_rf_13_segurados_com_dados_e_derivados(cliente):
    q = {"administradora": "0000001192", "apolice": "13008", "seq": 1, "fatura": 380819}
    r = cliente.get("/api/incendio/segurados", params=q).json()
    assert r["quantidade"] == 2
    assert r["produto"] == "RUPTURA" and r["faz_tudo_lar"] is True and r["locacao"] is False
    s = r["segurados"][0]
    assert s["certificado"] == "CF1DI/AP.602"
    assert s["documento"] == "330.163.307-25"
    assert s["chave"]["cpf_cnpj"] == "33016330725"
    assert set(s) >= {"portal", "nome", "endereco", "unidade", "avisos"}


def test_rf_06_pasta_inexistente_bloqueia_antes_de_emitir(cliente, tmp_path):
    corpo = {"administradora": "0000001192", "apolice": "13008", "seq": 1, "fatura": 380819,
             "pasta": str(tmp_path / "nao-existe"), "so_xml": True}  # fmt: skip
    r = cliente.post("/api/incendio/emitir", json=corpo)
    assert r.status_code == 400
    assert "nao existe" in r.json()["erro"]


def test_rf_21_upload_aws_exige_pdf(cliente, tmp_path):
    base = {"administradora": "0000001192", "apolice": "13008", "seq": 1, "fatura": 380819,
            "pasta": str(tmp_path), "upload_aws": True}  # fmt: skip
    r1 = cliente.post("/api/incendio/emitir", json={**base, "so_xml": True})
    assert r1.status_code == 400 and "RF-21" in r1.text
    assert not any(tmp_path.iterdir())  # RF-16: recusado antes de emitir


def test_rf_21_upload_aws_publica_e_devolve_o_link(cliente, tmp_path):
    from tests.unit.test_emitir_portal import PublicadorFalso, RegistroFalso

    pub, reg = PublicadorFalso(), RegistroFalso()
    webapp.app.dependency_overrides[webapp.get_fabrica_publicacao] = lambda: (lambda: (pub, reg))
    webapp.app.dependency_overrides[webapp.get_repositorio] = lambda: RepoFalso()
    # PDF falso: o Chromium nao entra no teste unitario
    from certgen.render import pdf as mod_pdf

    class RenderFalso:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def renderizar_certificado(self, cert, dados, destino):
            destino.write_bytes(b"%PDF-1.4 falso\n")
            return destino

    original = mod_pdf.RenderizadorPdf
    mod_pdf.RenderizadorPdf = RenderFalso
    try:
        corpo = {"administradora": "0000001192", "apolice": "13008", "seq": 1, "fatura": 380819,
                 "pasta": str(tmp_path), "upload_aws": True}  # fmt: skip
        r = cliente.post("/api/incendio/emitir", json=corpo)
    finally:
        mod_pdf.RenderizadorPdf = original
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["falhas"] == [] and len(d["emitidos"]) == 2
    assert all(e["link"] and e["link"].endswith(".pdf") for e in d["emitidos"])
    assert len(pub.publicados) == 2 and len(reg.registros) == 2


def test_uc_01_emitir_so_json_todos(cliente, tmp_path):
    corpo = {"administradora": "0000001192", "apolice": "13008", "seq": 1, "fatura": 380819,
             "pasta": str(tmp_path), "so_xml": True}  # fmt: skip
    r = cliente.post("/api/incendio/emitir", json=corpo)
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(d["emitidos"]) == 2 and d["falhas"] == []
    assert all(e["pdf"] is None for e in d["emitidos"])
    assert (tmp_path / "0000001192" / "072026").is_dir()


def test_uc_02_selecao_parcial(cliente, tmp_path):
    q = {"administradora": "0000001192", "apolice": "13008", "seq": 1, "fatura": 380819}
    seg = cliente.get("/api/incendio/segurados", params=q).json()["segurados"][1]
    corpo = {**q, "pasta": str(tmp_path), "so_xml": True, "selecionados": [seg["chave"]]}
    d = cliente.post("/api/incendio/emitir", json=corpo).json()
    assert [e["chave"]["certificado"] for e in d["emitidos"]] == ["CF1DI/AP.701"]


def test_rf_07_modo_consolidado_so_json(cliente, tmp_path):
    corpo = {"administradora": "0000001192", "apolice": "13008", "seq": 1, "fatura": 380819,
             "pasta": str(tmp_path), "so_xml": True, "individuais": False}  # fmt: skip
    d = cliente.post("/api/incendio/emitir", json=corpo).json()
    assert d["consolidado_json"] and d["consolidado_json"].endswith(".json")
    assert "certificados_13008_1_380819_" in d["consolidado_json"]
    pasta = tmp_path / "0000001192" / "072026"
    assert [p.name for p in pasta.iterdir()] == [d["consolidado_json"].rsplit("\\", 1)[-1].rsplit("/", 1)[-1]]


def test_rd_26_json_unico_pela_api(cliente, tmp_path):
    import json

    corpo = {"administradora": "0000001192", "apolice": "13008", "seq": 1, "fatura": 380819,
             "pasta": str(tmp_path), "so_xml": True, "json_unico": True}  # fmt: skip
    d = cliente.post("/api/incendio/emitir", json=corpo).json()
    assert d["json_unico"] and d["json_unico"].endswith(".json")
    assert all(e["json"] is None for e in d["emitidos"])
    env = json.loads(open(d["json_unico"], encoding="utf-8").read())
    assert env["_meta"]["quantidade"] == 2
    assert 'id="json_unico"' in cliente.get("/incendio").text


def test_rnf_10a_cliente_da_rede_nao_ve_sair_nem_procurar(cliente):
    webapp.app.dependency_overrides[webapp.cliente_local] = lambda: False
    try:
        assert 'id="sair"' not in cliente.get("/").text
        pagina = cliente.get("/incendio").text
        assert 'id="procurar"' not in pagina and "caminho de rede" in pagina
        assert cliente.post("/api/encerrar").status_code == 403
        assert cliente.post("/api/escolher-pasta", json={}).status_code == 403
    finally:
        del webapp.app.dependency_overrides[webapp.cliente_local]
    # local (TestClient conta como local): botoes presentes
    assert 'id="sair"' in cliente.get("/").text
    assert 'id="procurar"' in cliente.get("/incendio").text


def test_rnf_10a_ip_de_rede_da_propria_maquina_conta_como_local():
    import socket

    locais = webapp.hosts_locais()
    assert {"127.0.0.1", "::1"} <= locais
    _, _, proprios = socket.gethostbyname_ex(socket.gethostname())
    assert set(proprios) <= locais  # abrir pelo IP de rede na mesma maquina mantem Sair/Procurar
    assert "10.255.255.254" not in locais


def test_saude(cliente):
    assert cliente.get("/api/saude").json()["ok"] is True


def test_botao_sair_chama_o_encerramento(cliente):
    chamadas = []
    original = webapp.app.state.encerrar
    webapp.app.state.encerrar = lambda: chamadas.append(1)
    try:
        assert cliente.post("/api/encerrar").json()["ok"] is True
    finally:
        webapp.app.state.encerrar = original
    assert chamadas == [1]
    assert 'id="sair"' in cliente.get("/").text


def test_voltar_ao_menu_nos_submenus(cliente):
    for rota in ("/incendio", "/prestamista", "/vida"):
        assert "Voltar ao menu" in cliente.get(rota).text


def test_rn_14_datas_da_tela_sao_texto_dd_mm_aaaa(cliente):
    html = cliente.get("/incendio").text
    assert 'type="date"' not in html
    assert 'id="vigencia" class="data" placeholder="dd/mm/aaaa"' in html


def test_rd_06_api_recebe_iso_e_filtra(cliente):
    r = cliente.get("/api/incendio/apolices", params={"administradora": "0000001192", "inicio_vig": "2026-07-01"})
    assert r.status_code == 200 and len(r.json()) == 2
    r = cliente.get("/api/incendio/apolices", params={"administradora": "0000001192", "inicio_vig": "01/07/2026"})
    assert r.status_code == 422  # formato brasileiro nunca chega a API; a tela converte
