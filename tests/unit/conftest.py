"""Fixtures da tela (ADR-08): SQLite de usuarios temporario, ADMIN semeado e cliente logado.

bcrypt com custo 4 nos testes (12 em producao) para a suite continuar rapida.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from certgen.web import app as webapp
from certgen.web import auth
from certgen.web.usuarios import RepositorioUsuarios

ADMIN_EMAIL = "admin@teste.local"
ADMIN_SENHA = "Senha123x"
HEADER_CSRF = {"X-Requested-With": "fetch"}


@pytest.fixture
def repo_usuarios(tmp_path_factory, monkeypatch):
    monkeypatch.setattr(auth, "RONDAS_BCRYPT", 4)
    auth.limite_login.limpar_tudo()
    auth.limite_login_ip.limpar_tudo()
    # pasta propria: varios testes exigem que o tmp_path deles fique vazio (RF-16)
    repo = RepositorioUsuarios(tmp_path_factory.mktemp("usuarios") / "usuarios.sqlite")
    repo.criar(
        "Admin Teste", ADMIN_EMAIL, auth.gerar_hash(ADMIN_SENHA), "ADMIN", trocar_senha=False
    )
    webapp.app.state.usuarios = repo
    yield repo
    webapp.app.state.usuarios = None
    repo.fechar()


@pytest.fixture
def cliente_anonimo(repo_usuarios):
    with TestClient(webapp.app) as c:
        c.headers.update(HEADER_CSRF)
        yield c


@pytest.fixture
def cliente_logado(cliente_anonimo):
    r = cliente_anonimo.post(
        "/api/auth/login", json={"email": ADMIN_EMAIL, "senha": ADMIN_SENHA}
    )
    assert r.status_code == 200, r.text
    return cliente_anonimo
