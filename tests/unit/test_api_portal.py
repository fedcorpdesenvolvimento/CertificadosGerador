"""Fase 8 — APIs do portal com adaptadores falsos (RF-18, RF-20, RN-30, RF-19, RD-29)."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from certgen.config.settings import Config, ConfiguracaoAusente
from certgen.web import api_portal
from tests.unit.test_emitir_portal import (
    LINHA_13008,
    PublicadorFalso,
    RegistroFalso,
    RepoFalso,
    render_falso,
)

CHAVE = "95b9603782c9758eeddf62f24d822639"[::-1]  # 32 hex; nao e a chave real


@contextmanager
def _fabrica_falsa():
    yield render_falso


@pytest.fixture
def cliente(tmp_path):
    cfg = Config(
        repositorio="firebird", firebird=None, api_base_url="", api_token="",
        pasta_saida=tmp_path, api_key=CHAVE,
    )  # fmt: skip
    pub, reg = PublicadorFalso(), RegistroFalso()
    ov = api_portal.app.dependency_overrides
    ov[api_portal.get_config] = lambda: cfg
    ov[api_portal.get_api_key] = lambda: CHAVE
    ov[api_portal.get_repositorio] = lambda: RepoFalso([LINHA_13008])
    ov[api_portal.get_publicador] = lambda: pub
    ov[api_portal.get_registro] = lambda: reg
    ov[api_portal.get_fabrica_render] = lambda: _fabrica_falsa
    with TestClient(api_portal.app) as c:
        c.pub, c.reg = pub, reg
        yield c
    ov.clear()


PEDIDO = {"administradora": "0000001192", "cpf_cnpj": "330.163.307-25", "vigencia": "2026-07-01"}


def test_rn_30_sem_chave_ou_chave_errada_e_401_sem_tocar_nada(cliente):
    assert cliente.get("/v1/saude").status_code == 401
    r = cliente.post("/v1/certificados/emitir", json=PEDIDO, headers={"X-API-Key": "errada"})
    assert r.status_code == 401
    assert CHAVE not in r.text  # a chave nunca aparece na resposta
    assert cliente.pub.publicados == [] and cliente.reg.registros == []


def test_rf_18_saude_com_chave(cliente):
    r = cliente.get("/v1/saude", headers={"X-API-Key": CHAVE})
    assert r.status_code == 200 and r.json()["ok"] is True


def test_uc_12_emite_e_devolve_link(cliente, tmp_path):
    r = cliente.post("/v1/certificados/emitir", json=PEDIDO, headers={"X-API-Key": CHAVE})
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["pedido"]["cpf_cnpj"] == "33016330725"
    assert corpo["quantidade"] == 1
    [item] = corpo["certificados"]
    assert item["situacao"] == "publicado"
    assert item["link"].startswith("https://certincendioaws.s3.us-east-2.amazonaws.com/")
    assert item["chave"]["certificado"] == "CF1DI/AP.602"
    assert len(cliente.reg.registros) == 1
    assert list(Path(tmp_path).rglob("*.pdf"))  # RN-34: copia local
    # RD-29: o JSON espelho vem embutido, identico ao gravado em disco
    [js] = Path(tmp_path).rglob("*.json")
    assert item["documento"] == json.loads(js.read_text(encoding="utf-8"))
    assert item["documento"]["arquivo"]["link"] == item["link"]


def test_rd_27_nao_encontrado_e_404(cliente):
    r = cliente.post(
        "/v1/certificados/emitir",
        json={**PEDIDO, "vigencia": "2026-08-01"},
        headers={"X-API-Key": CHAVE},
    )
    assert r.status_code == 404
    assert cliente.pub.publicados == []


def test_rf_18_corpo_invalido(cliente):
    r = cliente.post(
        "/v1/certificados/emitir",
        json={**PEDIDO, "cpf_cnpj": "123"},
        headers={"X-API-Key": CHAVE},
    )
    assert r.status_code == 400
    r = cliente.post(
        "/v1/certificados/emitir",
        json={**PEDIDO, "vigencia": "01/07/2026"},
        headers={"X-API-Key": CHAVE},
    )
    assert r.status_code == 422  # pydantic: data nao ISO


def test_todos_falharam_e_502(cliente):
    cliente.pub.falhar = True
    r = cliente.post("/v1/certificados/emitir", json=PEDIDO, headers={"X-API-Key": CHAVE})
    assert r.status_code == 502
    assert r.json()["certificados"][0]["situacao"] == "falha"


def test_rn_30_sem_api_key_configurada_recusa():
    cfg = Config(
        repositorio="firebird", firebird=None, api_base_url="", api_token="",
        pasta_saida=Path("."), api_key="",
    )  # fmt: skip
    with pytest.raises(ConfiguracaoAusente):
        cfg.exigir_api_key()
    assert "***" not in repr(cfg) and CHAVE not in repr(cfg)


# ------------------------------------------------------------------ RF-20 (UC-13)
VERIFICACAO = {"administradora": "0000001192", "cpf_cnpj": "330.163.307-25"}


def _fixar_hoje(monkeypatch, ano, mes, dia):
    from datetime import date as _date

    class Hoje(_date):
        @classmethod
        def today(cls):
            return cls(ano, mes, dia)

    monkeypatch.setattr(api_portal, "date", Hoje)


def test_rf_20_verificar_exige_chave(cliente):
    assert cliente.post("/v1/segurados/verificar", json=VERIFICACAO).status_code == 401
    r = cliente.post("/v1/segurados/verificar", json=VERIFICACAO, headers={"X-API-Key": "x"})
    assert r.status_code == 401 and CHAVE not in r.text


def test_rf_20_verificar_devolve_so_o_booleano(cliente, monkeypatch):
    # LINHA_13008 vigora de 2026-07-01 a 2026-07-31 (RN-35: hoje dentro/fora)
    _fixar_hoje(monkeypatch, 2026, 7, 15)
    r = cliente.post("/v1/segurados/verificar", json=VERIFICACAO, headers={"X-API-Key": CHAVE})
    assert r.status_code == 200
    assert r.json() == {"existe": True}  # nada alem do booleano

    _fixar_hoje(monkeypatch, 2026, 8, 1)
    r = cliente.post("/v1/segurados/verificar", json=VERIFICACAO, headers={"X-API-Key": CHAVE})
    assert r.status_code == 200 and r.json() == {"existe": False}

    _fixar_hoje(monkeypatch, 2026, 7, 15)
    r = cliente.post(
        "/v1/segurados/verificar",
        json={**VERIFICACAO, "cpf_cnpj": "055.543.637-33"},
        headers={"X-API-Key": CHAVE},
    )
    assert r.status_code == 200 and r.json() == {"existe": False}
    assert cliente.pub.publicados == [] and cliente.reg.registros == []  # so leitura


def test_rf_20_verificar_corpo_invalido(cliente):
    r = cliente.post(
        "/v1/segurados/verificar",
        json={**VERIFICACAO, "cpf_cnpj": "123"},
        headers={"X-API-Key": CHAVE},
    )
    assert r.status_code == 400 and "erro" in r.json()
    r = cliente.post(
        "/v1/segurados/verificar", json={"administradora": "x"}, headers={"X-API-Key": CHAVE}
    )
    assert r.status_code == 422
