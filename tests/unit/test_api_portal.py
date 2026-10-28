"""Fase 8 / ADR-09 — APIs do portal com adaptadores falsos (RF-18, RF-20, RN-30 revisto,
RF-19, RD-29, GAP-23/24/26 fechados): chaves com escopo, envelope de erro, request id,
limite de taxa, link assinado e link sob demanda."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from certgen.config.settings import Config
from certgen.domain.certificado import Administradora
from certgen.web import api_portal, auth
from certgen.web.chaves_api import RepositorioChaves
from tests.unit.test_emitir_portal import (
    LINHA_13008,
    PublicadorFalso,
    RegistroFalso,
    RepoFalso,
    render_falso,
)

CHAVE = "95b9603782c9758eeddf62f24d822639"[::-1]  # chave de transicao (CERTGEN_API_KEY)


class RepoFalsoComAdms(RepoFalso):
    def listar_administradoras(self):
        return [
            Administradora("0000001192", "IMODATA ADM", None),
            Administradora("0000000019", "PROTEST", "19PAEL", possui_portal=True),
        ]


@contextmanager
def _fabrica_falsa():
    yield render_falso


@pytest.fixture
def chaves(tmp_path_factory):
    repo = RepositorioChaves(tmp_path_factory.mktemp("chaves") / "chaves.sqlite")
    yield repo
    repo.fechar()


@pytest.fixture
def cliente(tmp_path, chaves):
    cfg = Config(
        repositorio="firebird", firebird=None, api_base_url="", api_token="",
        pasta_saida=tmp_path, api_key=CHAVE,
    )  # fmt: skip
    pub, reg = PublicadorFalso(), RegistroFalso()
    auth.limite_api_chave.limpar_tudo()
    auth.limite_api_chave_errada.limpar_tudo()
    ov = api_portal.app.dependency_overrides
    ov[api_portal.get_config] = lambda: cfg
    ov[api_portal.get_api_key] = lambda: CHAVE
    ov[api_portal.get_repositorio_chaves] = lambda: chaves
    ov[api_portal.get_repositorio] = lambda: RepoFalsoComAdms([LINHA_13008])
    ov[api_portal.get_publicador] = lambda: pub
    ov[api_portal.get_registro] = lambda: reg
    ov[api_portal.get_fabrica_render] = lambda: _fabrica_falsa
    with TestClient(api_portal.app) as c:
        c.pub, c.reg, c.chaves = pub, reg, chaves
        yield c
    ov.clear()


H = {"X-API-Key": CHAVE}
PEDIDO = {"administradora": "0000001192", "cpf_cnpj": "330.163.307-25", "vigencia": "2026-07-01"}
VERIFICACAO = {"administradora": "0000001192", "cpf_cnpj": "330.163.307-25"}


def _envelope(r, status, codigo):
    assert r.status_code == status, r.text
    corpo = r.json()
    assert set(corpo) == {"codigo", "mensagem", "request_id", "detalhes"}
    assert corpo["codigo"] == codigo
    assert corpo["request_id"] == r.headers["X-Request-Id"]
    return corpo


# ------------------------------------------------------------------ RN-30 / ADR-09
def test_rn_30_sem_chave_ou_chave_errada_e_401_no_envelope_sem_tocar_nada(cliente):
    _envelope(cliente.get("/v1/saude"), 401, "CHAVE_INVALIDA")
    r = cliente.post("/v1/certificados/emitir", json=PEDIDO, headers={"X-API-Key": "errada"})
    _envelope(r, 401, "CHAVE_INVALIDA")
    assert CHAVE not in r.text  # a chave nunca aparece na resposta
    assert cliente.pub.publicados == [] and cliente.reg.registros == []


def test_rf_18_saude_com_chave_de_transicao_mostra_escopo(cliente):
    r = cliente.get("/v1/saude", headers=H)
    assert r.status_code == 200 and r.json()["ok"] is True
    assert r.json()["administradoras"] == "todas"
    assert r.headers["X-Request-Id"]


def test_adr_09_chave_cadastrada_com_escopo_e_403_fora_dele(cliente):
    registro, texto = cliente.chaves.criar("Portal X", ["19"])  # zfill -> 0000000019
    h = {"X-API-Key": texto}
    r = cliente.get("/v1/saude", headers=h)
    assert r.status_code == 200
    assert r.json()["cliente"] == "Portal X" and r.json()["administradoras"] == ["0000000019"]
    # verificacao fora do escopo: 403 sem consultar nada
    corpo = _envelope(
        cliente.post("/v1/segurados/verificar", json=VERIFICACAO, headers=h),
        403, "ADMINISTRADORA_NAO_PERMITIDA",
    )  # fmt: skip
    assert corpo["detalhes"] == {"administradora": "0000001192"}
    _envelope(cliente.post("/v1/certificados/emitir", json=PEDIDO, headers=h), 403,
              "ADMINISTRADORA_NAO_PERMITIDA")  # fmt: skip
    assert cliente.pub.publicados == []
    # dentro do escopo (sem linhas para 0000000019): verificacao responde normalmente
    r = cliente.post(
        "/v1/segurados/verificar", json={**VERIFICACAO, "administradora": "0000000019"}, headers=h
    )
    assert r.status_code == 200 and r.json()["existe"] is False
    # /v1/administradoras lista so as do escopo
    r = cliente.get("/v1/administradoras", headers=h)
    assert r.status_code == 200
    assert [a["codigo"] for a in r.json()["administradoras"]] == ["0000000019"]
    assert r.json()["administradoras"][0]["possui_portal"] is True
    # ultimo uso registrado com IP, sem a chave
    atual = cliente.chaves.obter(registro.id)
    assert atual.ultimo_uso and atual.ultimo_ip == "testclient"
    assert texto not in json.dumps(atual.publico())


def test_adr_09_chave_revogada_deixa_de_autenticar_na_hora(cliente):
    _, texto = cliente.chaves.criar("Portal Y", [], todas=True)
    h = {"X-API-Key": texto}
    assert cliente.get("/v1/saude", headers=h).status_code == 200
    cliente.chaves.revogar(cliente.chaves.listar()[0].id)
    _envelope(cliente.get("/v1/saude", headers=h), 401, "CHAVE_INVALIDA")


def test_adr_09_ip_fora_da_lista_e_403(cliente):
    _, texto = cliente.chaves.criar("Portal Z", [], todas=True, ips=["203.0.113.0/24"])
    # o TestClient chega como 'testclient' (nao e IP): fora da lista
    _envelope(cliente.get("/v1/saude", headers={"X-API-Key": texto}), 403, "ORIGEM_NAO_PERMITIDA")


def test_gap_26_limite_de_taxa_por_chave_e_429_com_retry_after(cliente, monkeypatch):
    monkeypatch.setattr(auth, "limite_api_chave", auth.LimiteTaxa(maximo=3, janela_seg=60))
    for _ in range(3):
        assert cliente.get("/v1/saude", headers=H).status_code == 200
    r = cliente.get("/v1/saude", headers=H)
    _envelope(r, 429, "LIMITE_EXCEDIDO")
    assert int(r.headers["Retry-After"]) >= 1


def test_gap_26_chaves_erradas_repetidas_bloqueiam_o_ip(cliente, monkeypatch):
    monkeypatch.setattr(
        auth, "limite_api_chave_errada", auth.LimiteTentativas(maximo=2, janela_seg=60)
    )
    for _ in range(2):
        _envelope(cliente.get("/v1/saude", headers={"X-API-Key": "x"}), 401, "CHAVE_INVALIDA")
    r = cliente.get("/v1/saude", headers={"X-API-Key": "x"})
    _envelope(r, 429, "LIMITE_EXCEDIDO")
    assert "Retry-After" in r.headers
    # a chave certa tambem espera: o bloqueio e por IP, antes de olhar a chave
    _envelope(cliente.get("/v1/saude", headers=H), 429, "LIMITE_EXCEDIDO")


def test_adr_09_request_id_do_portal_e_devolvido_ou_gerado(cliente):
    r = cliente.get("/v1/saude", headers={**H, "X-Request-Id": "portal-abc.123"})
    assert r.headers["X-Request-Id"] == "portal-abc.123"
    r = cliente.get("/v1/saude", headers={**H, "X-Request-Id": "inv alido <script>"})
    assert r.headers["X-Request-Id"] != "inv alido <script>"
    assert len(r.headers["X-Request-Id"]) == 32
    r = cliente.get("/v1/saude")  # tambem nos erros
    assert r.json()["request_id"] == r.headers["X-Request-Id"]


# ------------------------------------------------------------------ UC-12
def test_uc_12_emite_e_devolve_link_assinado_e_documento_com_link_permanente(cliente, tmp_path):
    r = cliente.post("/v1/certificados/emitir", json=PEDIDO, headers=H)
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["pedido"]["cpf_cnpj"] == "33016330725"
    assert corpo["quantidade"] == 1
    [item] = corpo["certificados"]
    assert item["situacao"] == "publicado"
    permanente = item["documento"]["arquivo"]["link"]
    assert permanente.startswith("https://certincendioaws.s3.us-east-2.amazonaws.com/")
    assert "?" not in permanente
    # ADR-09: o link entregue e assinado, derivado do permanente, com prazo
    assert item["link"].startswith(permanente + "?X-Amz-Expires=900")
    assert item["link_expira_em"].endswith("+00:00")
    assert item["chave"]["certificado"] == "CF1DI/AP.602"
    assert len(cliente.reg.registros) == 1
    assert cliente.reg.registros[0][1] == permanente  # o banco guarda o permanente (RD-20a)
    assert list(Path(tmp_path).rglob("*.pdf"))  # RN-34: copia local
    [js] = Path(tmp_path).rglob("*.json")  # RD-29: documento identico ao gravado
    assert item["documento"] == json.loads(js.read_text(encoding="utf-8"))


def test_rd_27_nao_encontrado_e_404_no_envelope(cliente):
    r = cliente.post(
        "/v1/certificados/emitir", json={**PEDIDO, "vigencia": "2026-08-01"}, headers=H
    )
    corpo = _envelope(r, 404, "CERTIFICADO_NAO_ENCONTRADO")
    assert corpo["detalhes"]["pedido"]["vigencia"] == "2026-08-01"
    assert cliente.pub.publicados == []


def test_rf_18_corpo_invalido_400_e_422_no_envelope(cliente):
    r = cliente.post("/v1/certificados/emitir", json={**PEDIDO, "cpf_cnpj": "123"}, headers=H)
    corpo = _envelope(r, 400, "PEDIDO_INVALIDO")
    assert "11 (CPF) ou 14 (CNPJ)" in corpo["mensagem"]
    r = cliente.post(
        "/v1/certificados/emitir", json={**PEDIDO, "vigencia": "01/07/2026"}, headers=H
    )
    corpo = _envelope(r, 422, "CORPO_MALFORMADO")  # pydantic: data nao ISO
    assert corpo["detalhes"]["campos"][0]["campo"] == "vigencia"


def test_todos_falharam_e_502_no_envelope_com_os_itens(cliente):
    cliente.pub.falhar = True
    r = cliente.post("/v1/certificados/emitir", json=PEDIDO, headers=H)
    corpo = _envelope(r, 502, "PUBLICACAO_FALHOU")
    assert corpo["detalhes"]["certificados"][0]["situacao"] == "falha"
    assert "S3 fora" in corpo["detalhes"]["certificados"][0]["motivo"]


def test_banco_indisponivel_e_503_banco(cliente):
    from certgen.adapters.firebird.conexao import ErroConexao

    class RepoFora(RepoFalsoComAdms):
        def listar_vigencias_portal(self, *a):
            raise ErroConexao("Nao foi possivel conectar")

    api_portal.app.dependency_overrides[api_portal.get_repositorio] = lambda: RepoFora([])
    r = cliente.post("/v1/segurados/verificar", json=VERIFICACAO, headers=H)
    corpo = _envelope(r, 503, "BANCO_INDISPONIVEL")
    assert "conectar" not in corpo["mensagem"]  # sem detalhe interno


def test_erro_inesperado_e_500_sem_vazar_detalhe(cliente):
    class RepoBug(RepoFalsoComAdms):
        def listar_vigencias_portal(self, *a):
            raise KeyError("segredo interno")

    api_portal.app.dependency_overrides[api_portal.get_repositorio] = lambda: RepoBug([])
    with TestClient(api_portal.app, raise_server_exceptions=False) as c:
        r = c.post("/v1/segurados/verificar", json=VERIFICACAO, headers=H)
    corpo = _envelope(r, 500, "ERRO_INTERNO")
    assert "segredo" not in r.text and corpo["request_id"]


# ------------------------------------------------------------------ RF-20 (UC-13)
def test_rf_20_verificar_exige_chave(cliente):
    _envelope(cliente.post("/v1/segurados/verificar", json=VERIFICACAO), 401, "CHAVE_INVALIDA")


def test_rf_20_verificar_devolve_existe_e_vigencias_rd_30(cliente):
    # LINHA_13008: vigencia 07/2026 ja encerrada; RN-35 (14/09/2026) nao olha vigencia
    r = cliente.post("/v1/segurados/verificar", json=VERIFICACAO, headers=H)
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["existe"] is True and corpo["quantidade"] == 1
    [c] = corpo["certificados"]
    assert c["nome"] == "JORGE EDUARDO MONT SERRAT"
    assert c["endereco"]["unidade"] == "AP.602" and c["endereco"]["uf"] == "RJ"
    assert (c["inicio_vig"], c["apolice"], c["seq"], c["fatura"], c["certificado"]) == (
        "2026-07-01", "13008", 0, 380819, "CF1DI/AP.602"
    )
    assert set(c["produto"]) == {"codigo", "nome", "descricao_fatura", "descricao_master"}

    r = cliente.post(
        "/v1/segurados/verificar", json={**VERIFICACAO, "cpf_cnpj": "055.543.637-33"}, headers=H
    )
    assert r.status_code == 200
    assert r.json() == {"existe": False, "quantidade": 0, "certificados": []}
    assert cliente.pub.publicados == [] and cliente.reg.registros == []  # so leitura


def test_rd_31_emitir_com_fatura_e_certificado(cliente):
    r = cliente.post(
        "/v1/certificados/emitir",
        json={**PEDIDO, "fatura": 380819, "certificado": "CF1DI/AP.602"},
        headers=H,
    )
    assert r.status_code == 200, r.text
    assert r.json()["pedido"]["fatura"] == 380819
    assert r.json()["certificados"][0]["situacao"] == "publicado"
    r = cliente.post(
        "/v1/certificados/emitir",
        json={**PEDIDO, "fatura": 380819, "certificado": "NAO-EXISTE"},
        headers=H,
    )
    _envelope(r, 404, "CERTIFICADO_NAO_ENCONTRADO")
    r = cliente.post("/v1/certificados/emitir", json={**PEDIDO, "fatura": "abc"}, headers=H)
    _envelope(r, 422, "CORPO_MALFORMADO")


def test_rf_20_verificar_corpo_invalido(cliente):
    r = cliente.post("/v1/segurados/verificar", json={**VERIFICACAO, "cpf_cnpj": "123"}, headers=H)
    _envelope(r, 400, "PEDIDO_INVALIDO")
    r = cliente.post("/v1/segurados/verificar", json={"administradora": "x"}, headers=H)
    _envelope(r, 422, "CORPO_MALFORMADO")
    # administradora maior que CHAR(10) (ex.: chaves literais) e 400, nao 500
    r = cliente.post(
        "/v1/segurados/verificar",
        json={"administradora": "{0000000019}", "cpf_cnpj": "{05554363733}"},
        headers=H,
    )
    corpo = _envelope(r, 400, "PEDIDO_INVALIDO")
    assert "10 caracteres" in corpo["mensagem"]


# ------------------------------------------------------------------ ADR-09: link sob demanda
def test_adr_09_link_sob_demanda_sem_reemitir(cliente):
    # linha sem link gravado: nao_emitido
    r = cliente.post("/v1/certificados/link", json=PEDIDO, headers=H)
    assert r.status_code == 200, r.text
    [item] = r.json()["certificados"]
    assert item["situacao"] == "nao_emitido" and item["link"] is None
    # depois de emitir, a linha tem link (RD-28): o endpoint assina sem publicar de novo
    assert cliente.post("/v1/certificados/emitir", json=PEDIDO, headers=H).status_code == 200
    publicados_antes = list(cliente.pub.publicados)
    permanente = cliente.reg.registros[0][1]
    api_portal.app.dependency_overrides[api_portal.get_repositorio] = lambda: RepoFalsoComAdms(
        [{**LINHA_13008, "link_certificado_aws": permanente}]
    )
    r = cliente.post("/v1/certificados/link", json=PEDIDO, headers=H)
    assert r.status_code == 200, r.text
    [item] = r.json()["certificados"]
    assert item["situacao"] == "disponivel"
    assert item["link"].startswith(permanente + "?X-Amz-Expires=900")
    assert item["link_expira_em"]
    assert cliente.pub.publicados == publicados_antes  # nada publicado
    # vigencia sem linha: 404
    r = cliente.post("/v1/certificados/link", json={**PEDIDO, "vigencia": "2020-01-01"}, headers=H)
    _envelope(r, 404, "CERTIFICADO_NAO_ENCONTRADO")


def test_adr_09_openapi_publicado_em_v1(cliente):
    r = cliente.get("/v1/openapi.json")
    assert r.status_code == 200
    caminhos = set(r.json()["paths"])
    assert {"/v1/saude", "/v1/segurados/verificar", "/v1/certificados/emitir",
            "/v1/certificados/link", "/v1/administradoras"} <= caminhos  # fmt: skip
    assert cliente.get("/v1/docs").status_code == 200
