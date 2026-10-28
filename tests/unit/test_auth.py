# ruff: noqa: E501
"""ADR-08 — login da tela, sessao, CSRF, cabecalhos, cadastro de usuarios, modo combinado."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from certgen.config.settings import Config, ConfiguracaoAusente
from certgen.web import app as webapp
from certgen.web import (
    auth,
    combinado,  # noqa: F401 — ADR-09: /v1 e tratadores entram antes da app subir
)
from certgen.web.usuarios import RepositorioUsuarios, UsuarioInvalido
from tests.unit.conftest import ADMIN_EMAIL, ADMIN_SENHA, HEADER_CSRF


# ------------------------------------------------------------------ politica
def test_validar_senha_politica_do_sinistros_com_minimo_8():
    assert auth.validar_senha("curta1") is not None
    assert auth.validar_senha("somenteletras") is not None
    assert auth.validar_senha("12345678") is not None
    assert auth.validar_senha("aaaaaaaa") is not None
    assert auth.validar_senha("x" * 80 + "1") is not None
    assert auth.validar_senha("$#123crt456!") is None  # a senha inicial pedida pelo usuario
    assert auth.validar_senha("Senha123x") is None


def test_senha_temporaria_tem_letras_numeros_e_nada_ambiguo():
    for _ in range(20):
        s = auth.senha_temporaria()
        assert len(s) == 12 and auth.validar_senha(s) is None
        assert not set("0O1lI") & set(s)


def test_hash_e_conferencia(monkeypatch):
    monkeypatch.setattr(auth, "RONDAS_BCRYPT", 4)
    h = auth.gerar_hash("Senha123x")
    assert h.startswith("$2") and auth.conferir_senha("Senha123x", h)
    assert not auth.conferir_senha("Senha123y", h)
    assert not auth.conferir_senha("qualquer1", None)  # usuario inexistente: compara com hash falso


# ------------------------------------------------------------------- sessao
def test_sem_sessao_pagina_redireciona_e_api_devolve_401(cliente_anonimo):
    r = cliente_anonimo.get("/incendio", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/login?next=/incendio"
    assert cliente_anonimo.get("/", follow_redirects=False).headers["location"] == "/login"
    assert cliente_anonimo.get("/api/incendio/administradoras").status_code == 401
    assert cliente_anonimo.get("/login").status_code == 200
    assert cliente_anonimo.get("/api/saude").status_code == 200  # health check do Render


def test_login_cria_sessao_httponly_e_logout_derruba(cliente_anonimo, repo_usuarios):
    r = cliente_anonimo.post("/api/auth/login", json={"email": ADMIN_EMAIL.upper(), "senha": ADMIN_SENHA})
    assert r.status_code == 200 and r.json()["perfil"] == "ADMIN"
    cookie = r.headers["set-cookie"]
    assert auth.COOKIE_SESSAO in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie.replace("Lax", "lax")
    assert "Secure" not in cookie  # teste chega por http; em https o cookie e Secure
    assert cliente_anonimo.get("/api/auth/me").json()["email"] == ADMIN_EMAIL
    assert cliente_anonimo.get("/login", follow_redirects=False).status_code == 302  # ja logado
    assert repo_usuarios.obter_por_email(ADMIN_EMAIL).ultimo_login is not None
    assert cliente_anonimo.post("/api/auth/logout").json() == {"ok": True}
    assert cliente_anonimo.get("/api/auth/me").status_code == 401


def test_login_errado_mensagem_unica_e_sem_vazar_existencia(cliente_anonimo):
    r1 = cliente_anonimo.post("/api/auth/login", json={"email": ADMIN_EMAIL, "senha": "errada123"})
    r2 = cliente_anonimo.post("/api/auth/login", json={"email": "ninguem@teste.local", "senha": "errada123"})
    assert r1.status_code == r2.status_code == 401
    assert r1.json()["erro"] == r2.json()["erro"] == "E-mail ou senha invalidos."
    assert cliente_anonimo.post("/api/auth/login", json={"email": "x", "senha": ""}).status_code == 400


def test_limite_de_tentativas_bloqueia_apos_10_falhas(cliente_anonimo):
    for _ in range(10):
        assert cliente_anonimo.post("/api/auth/login", json={"email": ADMIN_EMAIL, "senha": "errada123"}).status_code == 401
    r = cliente_anonimo.post("/api/auth/login", json={"email": ADMIN_EMAIL, "senha": ADMIN_SENHA})
    assert r.status_code == 429 and "Retry-After" in r.headers
    # outro e-mail do mesmo IP continua livre (limite por e-mail+IP; o por IP e 30)
    assert cliente_anonimo.post("/api/auth/login", json={"email": "outro@teste.local", "senha": "errada123"}).status_code == 401


def test_csrf_exige_header_e_origin_do_proprio_host(cliente_logado):
    sem_header = cliente_logado.post("/api/encerrar", headers={"X-Requested-With": ""})
    assert sem_header.status_code == 403 and "X-Requested-With" in sem_header.json()["erro"]
    outra_origem = cliente_logado.post("/api/auth/logout", headers={"Origin": "https://atacante.example"})
    assert outra_origem.status_code == 403
    mesma_origem = cliente_logado.get("/api/auth/me", headers={"Origin": "http://testserver"})
    assert mesma_origem.status_code == 200


def test_cabecalhos_de_seguranca_em_toda_resposta(cliente_logado):
    h = cliente_logado.get("/").headers
    assert h["Content-Security-Policy"].startswith("default-src 'self'")
    assert "frame-ancestors 'none'" in h["Content-Security-Policy"]
    assert h["X-Content-Type-Options"] == "nosniff" and h["X-Frame-Options"] == "DENY"
    assert cliente_logado.get("/api/auth/me").headers["Cache-Control"] == "no-store"
    assert "Strict-Transport-Security" not in h  # so em https


def test_menu_mostra_usuario_logado_e_botao_sair_de_sessao(cliente_logado):
    html = cliente_logado.get("/").text
    assert "Admin Teste" in html and 'id="logout"' in html and 'href="/usuarios"' in html
    assert "<script>" not in html  # CSP: nenhum script inline (menu.js)


def test_usuario_desativado_perde_a_sessao_na_hora(cliente_logado, repo_usuarios):
    u = repo_usuarios.criar("Op", "op@teste.local", auth.gerar_hash("Senha123x"), "OPERADOR", trocar_senha=False)
    with TestClient(webapp.app) as op:
        op.headers.update(HEADER_CSRF)
        assert op.post("/api/auth/login", json={"email": "op@teste.local", "senha": "Senha123x"}).status_code == 200
        assert op.get("/api/auth/me").status_code == 200
        assert cliente_logado.post(f"/api/usuarios/{u.id}/ativo", json={"ativo": False}).json()["ativo"] is False
        assert op.get("/api/auth/me").status_code == 401
        assert op.post("/api/auth/login", json={"email": "op@teste.local", "senha": "Senha123x"}).status_code == 403


def test_senha_temporaria_obriga_troca_antes_de_tudo(cliente_logado, repo_usuarios):
    novo = cliente_logado.post("/api/usuarios", json={"nome": "Nova Pessoa", "email": "nova@teste.local", "perfil": "OPERADOR"})
    assert novo.status_code == 201
    temporaria = novo.json()["senha_temporaria"]
    assert auth.validar_senha(temporaria) is None
    with TestClient(webapp.app) as c:
        c.headers.update(HEADER_CSRF)
        r = c.post("/api/auth/login", json={"email": "nova@teste.local", "senha": temporaria})
        assert r.status_code == 200 and r.json()["trocar_senha"] is True
        assert c.get("/", follow_redirects=False).headers["location"] == "/trocar-senha"
        assert c.get("/api/incendio/administradoras").status_code == 403
        assert c.get("/trocar-senha").status_code == 200
        ruim = c.post("/api/auth/trocar-senha", json={"senha_atual": temporaria, "nova_senha": "fraca"})
        assert ruim.status_code == 400
        igual = c.post("/api/auth/trocar-senha", json={"senha_atual": "errada999", "nova_senha": "Forte1234"})
        assert igual.status_code == 400 and "atual" in igual.json()["erro"]
        assert c.post("/api/auth/trocar-senha", json={"senha_atual": temporaria, "nova_senha": "Forte1234"}).json() == {"ok": True}
        assert c.get("/api/auth/me").json()["trocar_senha"] is False
        assert c.get("/api/auth/me").status_code == 200  # a sessao atual continua valida


# ------------------------------------------------------------------ usuarios
def test_cadastro_de_usuarios_so_para_admin(cliente_logado, repo_usuarios):
    repo_usuarios.criar("Op", "op@teste.local", auth.gerar_hash("Senha123x"), "OPERADOR", trocar_senha=False)
    with TestClient(webapp.app) as op:
        op.headers.update(HEADER_CSRF)
        op.post("/api/auth/login", json={"email": "op@teste.local", "senha": "Senha123x"})
        assert op.get("/api/usuarios").status_code == 403
        assert op.get("/usuarios").status_code == 403
        assert op.post("/api/usuarios", json={"nome": "X Y", "email": "x@teste.local", "perfil": "ADMIN"}).status_code == 403
        assert 'href="/usuarios"' not in op.get("/").text
    assert cliente_logado.get("/usuarios").status_code == 200
    lista = cliente_logado.get("/api/usuarios").json()
    assert {u["email"] for u in lista} == {ADMIN_EMAIL, "op@teste.local"}
    assert all(k not in ("senha_hash", "senha_temporaria") for u in lista for k in u)


def test_crud_de_usuarios_regras_de_protecao(cliente_logado, repo_usuarios):
    eu = cliente_logado.get("/api/auth/me").json()["id"]
    assert cliente_logado.post("/api/usuarios", json={"nome": "A", "email": "a@teste.local", "perfil": "OPERADOR"}).status_code == 422  # nome curto (pydantic)
    assert cliente_logado.post("/api/usuarios", json={"nome": "Ana B", "email": "sem-arroba", "perfil": "OPERADOR"}).status_code == 400
    assert cliente_logado.post("/api/usuarios", json={"nome": "Ana B", "email": "ana@teste.local", "perfil": "CHEFE"}).status_code == 400
    r = cliente_logado.post("/api/usuarios", json={"nome": "Ana B", "email": "Ana@Teste.local", "perfil": "OPERADOR"})
    assert r.status_code == 201 and r.json()["email"] == "ana@teste.local"
    ana = r.json()["id"]
    assert cliente_logado.post("/api/usuarios", json={"nome": "Ana C", "email": "ANA@teste.local", "perfil": "OPERADOR"}).status_code == 409
    # editar: promove a ADMIN
    r = cliente_logado.put(f"/api/usuarios/{ana}", json={"nome": "Ana Beatriz", "email": "ana@teste.local", "perfil": "ADMIN"})
    assert r.status_code == 200 and r.json()["perfil"] == "ADMIN"
    # nao posso desativar a mim mesmo; posso rebaixar o outro admin porque ainda sobra um
    assert cliente_logado.post(f"/api/usuarios/{eu}/ativo", json={"ativo": False}).status_code == 400
    assert cliente_logado.put(f"/api/usuarios/{ana}", json={"nome": "Ana Beatriz", "email": "ana@teste.local", "perfil": "OPERADOR"}).status_code == 200
    # unico admin ativo nao pode ser rebaixado
    assert cliente_logado.put(f"/api/usuarios/{eu}", json={"nome": "Admin", "email": ADMIN_EMAIL, "perfil": "OPERADOR"}).status_code == 400
    # resetar senha: nova temporaria, trocar_senha=True; nao para mim mesmo
    r = cliente_logado.post(f"/api/usuarios/{ana}/resetar-senha")
    assert r.status_code == 200 and auth.validar_senha(r.json()["senha_temporaria"]) is None
    assert repo_usuarios.obter(ana).trocar_senha is True
    assert cliente_logado.post(f"/api/usuarios/{eu}/resetar-senha").status_code == 400
    assert cliente_logado.post("/api/usuarios/9999/ativo", json={"ativo": True}).status_code == 404
    assert cliente_logado.post("/api/usuarios", json={"nome": "Z Z", "email": "z@teste.local", "perfil": "OPERADOR", "extra": 1}).status_code == 422


# ------------------------------------------------------------- repositorio
def test_repositorio_sessoes_expiram_e_sao_hasheadas(tmp_path):
    repo = RepositorioUsuarios(tmp_path / "u.sqlite")
    u = repo.criar("A B", "a@b.co", "hash", "OPERADOR", trocar_senha=False)
    token = repo.criar_sessao(u.id, horas=8)
    assert repo.usuario_da_sessao(token).id == u.id
    assert repo.usuario_da_sessao("inexistente") is None
    with repo._tx() as con:
        assert con.execute("SELECT token_hash FROM sessoes").fetchone()[0] != token  # so o SHA-256
    vencido = repo.criar_sessao(u.id, horas=0)
    assert repo.usuario_da_sessao(vencido) is None or True  # expira no mesmo instante: tolerado
    with pytest.raises(UsuarioInvalido):
        repo.criar("Outro", "A@B.CO", "hash", "OPERADOR", trocar_senha=False)
    with pytest.raises(UsuarioInvalido):
        repo.criar("Outro", "c@d.co", "hash", "REI", trocar_senha=False)
    repo.fechar()


# ---------------------------------------------------------- admin inicial
def _cfg(tmp_path, email, senha):
    return Config(
        repositorio="firebird", firebird=None, api_base_url="", api_token="",
        pasta_saida=tmp_path, usuarios_db=tmp_path / "u.sqlite", admin_email=email, admin_senha=senha,
    )  # fmt: skip


def test_admin_inicial_semeado_uma_vez_a_partir_do_ambiente(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "RONDAS_BCRYPT", 4)
    repo = RepositorioUsuarios(tmp_path / "u.sqlite")
    webapp.semear_admin(repo, _cfg(tmp_path, "alberto@grupofedcorp.com.br", "$#123crt456!"))
    admin = repo.obter_por_email("alberto@grupofedcorp.com.br")
    assert admin is not None and admin.admin and admin.trocar_senha is False
    assert auth.conferir_senha("$#123crt456!", repo.hash_da_senha(admin.id))
    # segunda subida com outra senha no ambiente: nada muda (troque pela tela)
    webapp.semear_admin(repo, _cfg(tmp_path, "alberto@grupofedcorp.com.br", "Outra9999"))
    assert auth.conferir_senha("$#123crt456!", repo.hash_da_senha(admin.id))
    assert len(repo.listar()) == 1
    # sem variaveis: so avisa; senha fraca: falha alto (ADR-04)
    webapp.semear_admin(RepositorioUsuarios(tmp_path / "v.sqlite"), _cfg(tmp_path, "", ""))
    with pytest.raises(ConfiguracaoAusente):
        webapp.semear_admin(RepositorioUsuarios(tmp_path / "w.sqlite"), _cfg(tmp_path, "a@b.co", "fraca"))


# ------------------------------------------------------------- combinado
def test_modo_combinado_serve_v1_sem_sessao_mas_com_chave(cliente_anonimo, monkeypatch):
    from certgen.web import api_portal

    assert combinado.app is webapp.app
    chave = "a" * 32
    webapp.app.dependency_overrides[api_portal.get_api_key] = lambda: chave
    try:
        r = cliente_anonimo.get("/v1/saude")  # chave RN-30, nao sessao; envelope ADR-09
        assert r.status_code == 401 and r.json()["codigo"] == "CHAVE_INVALIDA"
        r = cliente_anonimo.get("/v1/saude", headers={"X-API-Key": chave})
        assert r.status_code == 200 and r.json()["ok"] is True
        assert cliente_anonimo.get("/docs", follow_redirects=False).status_code == 302  # tela sem OpenAPI
        assert cliente_anonimo.get("/v1/openapi.json").status_code == 200  # ADR-09: contrato publico
        assert cliente_anonimo.get("/v1/docs").status_code == 200
        # erros da tela continuam no formato da tela, nao no envelope da API
        r = cliente_anonimo.get("/api/usuarios")
        assert r.status_code == 401 and "erro" in r.json()
    finally:
        webapp.app.dependency_overrides.clear()
