"""ADR-09 — cadastro de chaves da API: hash, escopo, IPs, revogacao e rotas da tela."""

from __future__ import annotations

import pytest

from certgen.web import app as webapp
from certgen.web.chaves_api import (
    ChaveInvalida,
    RepositorioChaves,
    hash_chave,
    normalizar_administradoras,
    normalizar_ips,
)


@pytest.fixture
def repo(tmp_path):
    r = RepositorioChaves(tmp_path / "chaves.sqlite")
    yield r
    r.fechar()


def test_criar_guarda_so_o_hash_e_devolve_o_texto_uma_vez(repo):
    registro, texto = repo.criar("Portal W2BIT", ["1192", "0000000019"], criada_por=1)
    assert texto.startswith("fc_") and len(texto) > 40
    assert registro.prefixo == texto[:8]
    assert registro.administradoras == ("0000001192", "0000000019")  # zfill + ordem
    assert registro.ativa and registro.criada_por == 1
    assert texto not in str(registro.publico())
    con = repo._con
    (guardado,) = con.execute("SELECT chave_hash FROM chaves_api").fetchone()
    assert guardado == hash_chave(texto) and guardado != texto


def test_autenticar_por_texto_e_recusar_errada_ou_revogada(repo):
    registro, texto = repo.criar("Alfa", [], todas=True)
    assert repo.autenticar(texto).id == registro.id
    assert repo.autenticar(texto + "x") is None
    assert repo.autenticar("") is None and repo.autenticar(None) is None
    repo.revogar(registro.id)
    assert repo.autenticar(texto) is None
    assert repo.obter(registro.id).revogada_em and repo.quantidade_ativas() == 0


def test_escopo_de_administradoras_e_ips():
    assert normalizar_administradoras(["19", " 1192 ", "", "19"]) == ["0000000019", "0000001192"]
    with pytest.raises(ChaveInvalida):
        normalizar_administradoras(["abc"])
    with pytest.raises(ChaveInvalida):
        normalizar_administradoras(["12345678901"])
    assert normalizar_ips(["203.0.113.10", "198.51.100.0/24", ""]) == [
        "203.0.113.10/32", "198.51.100.0/24"
    ]  # fmt: skip
    with pytest.raises(ChaveInvalida):
        normalizar_ips(["nao-e-ip"])


def test_permite_administradora_e_ip(repo):
    registro, _ = repo.criar("Beta", ["19"], ips=["198.51.100.0/24"])
    assert registro.permite_administradora("19") and registro.permite_administradora("0000000019")
    assert not registro.permite_administradora("0000001192")
    assert registro.permite_ip("198.51.100.7") and not registro.permite_ip("203.0.113.1")
    assert not registro.permite_ip(None) and not registro.permite_ip("testclient")
    todas, _ = repo.criar("Gama", [], todas=True)
    assert todas.permite_administradora("qualquer") and todas.permite_ip("testclient")


def test_criar_exige_nome_e_escopo(repo):
    with pytest.raises(ChaveInvalida):
        repo.criar("", ["19"])
    with pytest.raises(ChaveInvalida):
        repo.criar("Sem escopo", [])


def test_atualizar_muda_escopo_sem_trocar_a_chave(repo):
    registro, texto = repo.criar("Delta", ["19"])
    novo = repo.atualizar(registro.id, "D2", ["1192"], todas=False, ips=["203.0.113.1"])
    assert novo.nome == "D2" and novo.administradoras == ("0000001192",)
    assert novo.ips == ("203.0.113.1/32",)
    assert repo.autenticar(texto).id == registro.id  # mesma chave continua valendo


# ------------------------------------------------------------- rotas da tela
@pytest.fixture
def repo_chaves(tmp_path_factory):
    r = RepositorioChaves(tmp_path_factory.mktemp("chaves") / "chaves.sqlite")
    webapp.app.state.chaves = r
    yield r
    webapp.app.state.chaves = None
    r.fechar()


def test_tela_admin_cria_edita_e_revoga_chave(cliente_logado, repo_chaves):
    c = cliente_logado
    assert c.get("/chaves").status_code == 200
    r = c.post("/api/chaves", json={"nome": "Portal", "administradoras": ["19"]})
    assert r.status_code == 201, r.text
    criada = r.json()
    assert criada["chave"].startswith("fc_") and criada["administradoras"] == ["0000000019"]
    r = c.get("/api/chaves")
    assert r.status_code == 200 and len(r.json()) == 1 and "chave" not in r.json()[0]
    r = c.put(f"/api/chaves/{criada['id']}", json={"nome": "Portal 2", "todas": True})
    assert r.status_code == 200 and r.json()["todas"] is True
    r = c.post("/api/chaves", json={"nome": "Xis", "administradoras": []})
    assert r.status_code == 400  # sem escopo
    r = c.post(f"/api/chaves/{criada['id']}/revogar")
    assert r.status_code == 200 and r.json()["ativa"] is False
    assert repo_chaves.autenticar(criada["chave"]) is None
    assert c.post("/api/chaves/999/revogar").status_code == 404


def test_tela_operador_nao_ve_chaves(cliente_logado, repo_chaves, repo_usuarios):
    from certgen.web import auth

    repo_usuarios.criar("Op", "op@teste.local", auth.gerar_hash("Senha123x"), "OPERADOR",
                        trocar_senha=False)  # fmt: skip
    c = cliente_logado
    c.post("/api/auth/logout")
    r = c.post("/api/auth/login", json={"email": "op@teste.local", "senha": "Senha123x"})
    assert r.status_code == 200
    assert c.get("/api/chaves").status_code == 403
    assert c.get("/chaves").status_code == 403


def test_tela_sem_sessao_nao_acessa_chaves(cliente_anonimo, repo_chaves):
    assert cliente_anonimo.get("/api/chaves").status_code == 401
    assert cliente_anonimo.get("/chaves", follow_redirects=False).status_code == 302
