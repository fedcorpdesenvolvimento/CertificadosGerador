"""Fase 4 — API e paginas.

Menu com tres modulos (decisao do usuario, 03/09/2026 — ADR-07):
  /incendio      CERTIFICADO INCENDIO          -> este sistema (cascata 5.2, RF-01..RF-16)
  /prestamista   CERTIFICADO PRESTAMISTA/ALUG  -> sem especificacao ainda (GAP-21)
  /vida          CERTIFICADO VIDA              -> sem especificacao ainda (GAP-22)

RNF-10: servir apenas em 127.0.0.1 (ver `certgen web`).
ADR-08 (23/10/2026): toda pagina e toda rota /api/* exigem sessao (login por e-mail e
senha; modelo do Sistema de Sinistros FedCorp). Ver web/auth.py e web/usuarios.py.
RF-06: pasta de destino validada antes da emissao.
RF-09: a resposta traz emitidos e falhas com motivo.
Os endpoints sao `def` (sincronos): rodam no threadpool do Starlette, o que
permite usar a API sincrona do Playwright e do fdb sem bloquear o loop.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import date
from functools import lru_cache
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, ConfigDict, Field

from certgen import __version__
from certgen.application.emitir_certificados import (
    OpcoesEmissao,
    emitir_lote,
    validar_pasta_destino,
)
from certgen.application.listar_cascata import Cascata, rotulo_apolice
from certgen.application.ports import PublicadorArquivos, RegistroLinks, RepositorioCertificados
from certgen.config.settings import Config, ConfiguracaoAusente
from certgen.domain.certificado import ChaveCertificado, ChaveLote
from certgen.domain.nomes_arquivo import NomeArquivoInvalido
from certgen.domain.produto import ProdutoIndeterminado
from certgen.web import auth
from certgen.web.chaves_api import ChaveInvalida, RepositorioChaves
from certgen.web.usuarios import PERFIS, RepositorioUsuarios, Usuario, UsuarioInvalido

log = logging.getLogger("certgen.web")
PASTA_WEB = Path(__file__).parent
MODULOS = [
    {"slug": "incendio", "titulo": "CERTIFICADO INCENDIO", "ativo": True,
     "descricao": "Seguro incendio / conteudo: PDF + JSON a partir do Firebird."},
    {"slug": "prestamista", "titulo": "CERTIFICADO PRESTAMISTA/ALUG", "ativo": False,
     "descricao": "Em preparacao. Sem especificacao ainda (GAP-21)."},
    {"slug": "vida", "titulo": "CERTIFICADO VIDA", "ativo": False,
     "descricao": "Em preparacao. Sem especificacao ainda (GAP-22)."},
]  # fmt: skip

def semear_admin(repo: RepositorioUsuarios, cfg: Config) -> None:
    """ADR-08 — cria o ADMIN inicial a partir de CERTGEN_ADMIN_EMAIL/CERTGEN_ADMIN_SENHA
    apenas quando nao existe nenhum ADMIN ativo (modelo `migrate.js` do Sinistros).
    Depois disso as variaveis nao alteram a senha: troque pela tela."""
    if repo.existe_admin():
        return
    if not (cfg.admin_email and cfg.admin_senha):
        log.warning(
            "nenhum usuario ADMIN cadastrado e CERTGEN_ADMIN_EMAIL/CERTGEN_ADMIN_SENHA ausentes: "
            "ninguem consegue entrar na tela"
        )
        return
    if not auth.EMAIL_RE.match(cfg.admin_email):
        raise ConfiguracaoAusente("CERTGEN_ADMIN_EMAIL nao e um e-mail valido")
    motivo = auth.validar_senha(cfg.admin_senha)
    if motivo:
        raise ConfiguracaoAusente(f"CERTGEN_ADMIN_SENHA recusada: {motivo}")
    repo.criar(
        "Administrador do Sistema", cfg.admin_email, auth.gerar_hash(cfg.admin_senha), "ADMIN",
        trocar_senha=False,
    )  # fmt: skip
    auth.registrar_evento("admin_inicial_criado", email=cfg.admin_email)


@asynccontextmanager
async def _ciclo_de_vida(app: FastAPI) -> AsyncIterator[None]:
    """Abre o SQLite de usuarios na subida (testes injetam `app.state.usuarios` antes)."""
    if getattr(app.state, "usuarios", None) is None:
        cfg = _config()
        app.state.usuarios = RepositorioUsuarios(cfg.usuarios_db)
        semear_admin(app.state.usuarios, cfg)
    if getattr(app.state, "chaves", None) is None:  # ADR-09: mesmo arquivo dos usuarios
        # (sem ler o ambiente de novo: os testes injetam um SQLite temporario e nao tem .env)
        app.state.chaves = RepositorioChaves(app.state.usuarios.caminho)
    yield


# docs_url=None: a tela nao publica o seu OpenAPI (ADR-08); a API do portal tem o dela.
app = FastAPI(
    title="Gerador de Certificados", version=__version__, lifespan=_ciclo_de_vida,
    docs_url=None, redoc_url=None, openapi_url=None,
)  # fmt: skip
app.state.usuarios = None
app.state.chaves = None  # ADR-09
app.mount("/static", StaticFiles(directory=str(PASTA_WEB / "static")), name="static")
app.middleware("http")(auth.middleware_sessao)


@app.middleware("http")
async def _sem_cache_de_estaticos(request: Request, call_next):
    """15/09/2026: o navegador reutilizava incendio.js antigo e a tela nova nao enviava
    upload_aws. Estaticos sempre revalidam; a URL ainda leva ?v=<hash> (cache-busting)."""
    resposta = await call_next(request)
    if request.url.path.startswith("/static/"):
        resposta.headers["Cache-Control"] = "no-cache, must-revalidate"
    return resposta


@lru_cache(maxsize=1)
def versao_estatica() -> str:
    """Hash curto do conteudo de static/: muda a URL dos arquivos a cada alteracao."""
    h = hashlib.sha1()
    for arq in sorted((PASTA_WEB / "static").iterdir()):
        if arq.is_file():
            h.update(arq.name.encode())
            h.update(arq.read_bytes())
    return h.hexdigest()[:10]


@lru_cache(maxsize=1)
def _paginas() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(PASTA_WEB / "templates")),
        autoescape=select_autoescape(["html"]),
    )


def _pagina(nome: str, usuario: Usuario | None = None, **ctx) -> HTMLResponse:
    html = _paginas().get_template(nome).render(
        versao=__version__, v=versao_estatica(), modulos=MODULOS, usuario=usuario, **ctx
    )
    return HTMLResponse(html)


# --------------------------------------------------------------- dependencias
@lru_cache(maxsize=1)
def _config() -> Config:
    return Config.do_ambiente()


def get_repositorio() -> RepositorioCertificados:
    """Adaptador escolhido por CERTGEN_REPOSITORIO (ADR-01). Testes sobrescrevem."""
    cfg = _config()
    if cfg.repositorio == "firebird":
        from certgen.adapters.firebird.repositorio import RepositorioFirebird

        return RepositorioFirebird(susep_corretora=cfg.susep_corretora)
    raise HTTPException(501, f"adaptador '{cfg.repositorio}' ainda nao implementado (Fase 5)")


def get_config() -> Config:
    return _config()


FabricaPublicacao = Callable[[], tuple[PublicadorArquivos, RegistroLinks]]


def _publicacao_real() -> tuple[PublicadorArquivos, RegistroLinks]:
    """RF-21 — S3 (RN-29, credenciais AWS_* do .env, SEC-01) + registrar_link no Firebird
    (RD-20a). Construido so quando o operador marca Upload AWS."""
    from certgen.adapters.firebird.repositorio import RepositorioFirebird
    from certgen.adapters.s3.publicador import PublicadorS3

    cfg = _config()
    if cfg.repositorio != "firebird":
        raise HTTPException(501, "registro de links so existe no adaptador Firebird")
    return (
        PublicadorS3(bucket=cfg.aws_bucket, regiao=cfg.aws_region),
        RepositorioFirebird(susep_corretora=cfg.susep_corretora),
    )


def get_fabrica_publicacao() -> FabricaPublicacao:
    """Testes sobrescrevem para nao tocar S3 nem banco."""
    return _publicacao_real


@lru_cache(maxsize=1)
def hosts_locais() -> frozenset[str]:
    """Enderecos pelos quais o navegador da PROPRIA maquina do servidor pode chegar:
    loopback e todos os IPs de rede desta maquina (quem abre http://192.168.x.x:8000
    no mesmo computador chega com o IP de rede como origem, nao com 127.0.0.1)."""
    import socket

    ips = {"127.0.0.1", "::1", "localhost", "testclient"}
    try:
        _, _, proprios = socket.gethostbyname_ex(socket.gethostname())
        ips.update(proprios)
    except OSError:
        pass
    return frozenset(ips)


def cliente_local(request: Request) -> bool:
    """RNF-10a — True quando o navegador esta na mesma maquina do servidor.

    So o operador local pode encerrar o servidor (Sair) e abrir o dialogo nativo de
    pastas (Procurar...), que aparecem na tela da maquina do servidor. Quando a tela
    e compartilhada na rede (`certgen web --rede`), os demais usuarios nao veem
    esses botoes e a API os recusa.
    """
    host = request.client.host if request.client else ""
    return host in hosts_locais()


# ------------------------------------------------------------------- paginas
@app.get("/", response_class=HTMLResponse)
def menu(
    local: bool = Depends(cliente_local), usuario: Usuario = Depends(auth.usuario_atual)
) -> HTMLResponse:
    return _pagina("menu.html", usuario, local=local)


@app.get("/incendio", response_class=HTMLResponse)
def pagina_incendio(
    cfg: Config = Depends(get_config),
    local: bool = Depends(cliente_local),
    usuario: Usuario = Depends(auth.usuario_atual),
) -> HTMLResponse:
    return _pagina(
        "incendio.html", usuario, pasta_padrao=str(cfg.pasta_saida), modulo=MODULOS[0],
        local=local,
    )  # fmt: skip


@app.get("/prestamista", response_class=HTMLResponse)
def pagina_prestamista(usuario: Usuario = Depends(auth.usuario_atual)) -> HTMLResponse:
    return _pagina("em_construcao.html", usuario, modulo=MODULOS[1])


@app.get("/vida", response_class=HTMLResponse)
def pagina_vida(usuario: Usuario = Depends(auth.usuario_atual)) -> HTMLResponse:
    return _pagina("em_construcao.html", usuario, modulo=MODULOS[2])


# ------------------------------------------------------- ADR-08: autenticacao
@app.get("/login", response_class=HTMLResponse)
def pagina_login(request: Request) -> Response:
    if getattr(request.state, "usuario", None) is not None:
        return RedirectResponse("/", status_code=302)
    return _pagina("login.html")


@app.get("/trocar-senha", response_class=HTMLResponse)
def pagina_trocar_senha(usuario: Usuario = Depends(auth.usuario_atual)) -> HTMLResponse:
    return _pagina("trocar_senha.html", usuario)


@app.get("/usuarios", response_class=HTMLResponse)
def pagina_usuarios(usuario: Usuario = Depends(auth.exigir_admin)) -> HTMLResponse:
    return _pagina("usuarios.html", usuario, perfis=PERFIS)


@app.get("/chaves", response_class=HTMLResponse)
def pagina_chaves(usuario: Usuario = Depends(auth.exigir_admin)) -> HTMLResponse:
    """ADR-09 — chaves da API do portal (so ADMIN)."""
    return _pagina("chaves.html", usuario)


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str
    senha: str


@app.post("/api/auth/login")
def api_login(
    req: LoginIn, request: Request, repo: RepositorioUsuarios = Depends(auth.repositorio_usuarios)
):
    """Login por e-mail e senha (Sinistros `POST /api/auth/login`): limite de 10 falhas por
    e-mail+IP em 15 min, comparacao contra hash falso quando o e-mail nao existe, mensagem
    unica, sessao nova a cada login."""
    email = req.email.strip().lower()
    ip = auth.ip_de(request)
    chave = f"{ip}|{email}"
    if not auth.EMAIL_RE.match(email) or not req.senha:
        return _erro(ValueError("Informe e-mail e senha."), 400)
    espera = auth.limite_login.bloqueado(chave) or auth.limite_login_ip.bloqueado(ip)
    if espera:
        resposta = JSONResponse(
            {"erro": "Muitas tentativas. Aguarde 15 minutos e tente novamente."}, status_code=429
        )
        resposta.headers["Retry-After"] = str(espera)
        auth.registrar_evento("login_bloqueado", ip=ip, email=email)
        return resposta
    usuario = repo.obter_por_email(email)
    ok = auth.conferir_senha(req.senha, repo.hash_da_senha(usuario.id) if usuario else None)
    if usuario is None or not ok:
        auth.limite_login.registrar_falha(chave)
        auth.limite_login_ip.registrar_falha(ip)
        auth.registrar_evento("login_falhou", ip=ip, email=email)
        return _erro(ValueError("E-mail ou senha invalidos."), 401)
    if not usuario.ativo:
        auth.registrar_evento("login_desativado", ip=ip, usuario_id=usuario.id)
        return _erro(PermissionError("Usuario desativado. Procure o administrador."), 403)
    auth.limite_login.limpar(chave)
    token = repo.criar_sessao(usuario.id, auth.HORAS_SESSAO)
    repo.registrar_login(usuario.id)
    resposta = JSONResponse(usuario.publico())
    auth.gravar_cookie(resposta, request, token)
    auth.registrar_evento("login", ip=ip, usuario_id=usuario.id, perfil=usuario.perfil)
    return resposta


@app.post("/api/auth/logout")
def api_logout(request: Request, repo: RepositorioUsuarios = Depends(auth.repositorio_usuarios)):
    repo.encerrar_sessao(request.cookies.get(auth.COOKIE_SESSAO))
    resposta = JSONResponse({"ok": True})
    auth.apagar_cookie(resposta, request)
    return resposta


@app.get("/api/auth/me")
def api_me(usuario: Usuario = Depends(auth.usuario_atual)):
    return usuario.publico()


class TrocaSenhaIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    senha_atual: str
    nova_senha: str


@app.post("/api/auth/trocar-senha")
def api_trocar_senha(
    req: TrocaSenhaIn,
    request: Request,
    usuario: Usuario = Depends(auth.usuario_atual),
    repo: RepositorioUsuarios = Depends(auth.repositorio_usuarios),
):
    """Troca pela propria pessoa; obrigatoria quando a senha e temporaria. Encerra as outras
    sessoes do usuario e mantem a atual."""
    if not auth.conferir_senha(req.senha_atual, repo.hash_da_senha(usuario.id)):
        return _erro(ValueError("Senha atual incorreta."), 400)
    motivo = auth.validar_senha(req.nova_senha)
    if motivo:
        return _erro(ValueError(motivo), 400)
    if req.nova_senha == req.senha_atual:
        return _erro(ValueError("A nova senha deve ser diferente da atual."), 400)
    repo.definir_senha(
        usuario.id, auth.gerar_hash(req.nova_senha), trocar_senha=False,
        manter_token=request.cookies.get(auth.COOKIE_SESSAO),
    )  # fmt: skip
    auth.registrar_evento("senha_trocada", usuario_id=usuario.id)
    return {"ok": True}


# ------------------------------------------------ ADR-08: cadastro de usuarios
class UsuarioIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nome: str = Field(..., min_length=2, max_length=120)
    email: str = Field(..., max_length=160)
    perfil: str


def _validar_usuario_in(req: UsuarioIn) -> str | None:
    if not req.nome.strip():
        return "Informe o nome."
    if not auth.EMAIL_RE.match(req.email.strip().lower()):
        return "E-mail invalido."
    if req.perfil not in PERFIS:
        return f"Perfil invalido: use {', '.join(PERFIS)}."
    return None


@app.get("/api/usuarios")
def api_listar_usuarios(
    _: Usuario = Depends(auth.exigir_admin),
    repo: RepositorioUsuarios = Depends(auth.repositorio_usuarios),
):
    return [u.publico() for u in repo.listar()]


@app.post("/api/usuarios", status_code=201)
def api_criar_usuario(
    req: UsuarioIn,
    admin: Usuario = Depends(auth.exigir_admin),
    repo: RepositorioUsuarios = Depends(auth.repositorio_usuarios),
):
    """Cria com senha temporaria, mostrada UMA vez ao administrador (nao ha e-mail neste
    sistema); o usuario e obrigado a troca-la no primeiro acesso."""
    motivo = _validar_usuario_in(req)
    if motivo:
        return _erro(ValueError(motivo))
    temporaria = auth.senha_temporaria()
    try:
        novo = repo.criar(
            req.nome, req.email, auth.gerar_hash(temporaria), req.perfil, trocar_senha=True
        )
    except UsuarioInvalido as exc:
        return _erro(exc, 409)
    auth.registrar_evento("usuario_criado", por=admin.id, usuario_id=novo.id, perfil=novo.perfil)
    return JSONResponse({**novo.publico(), "senha_temporaria": temporaria}, status_code=201)


@app.put("/api/usuarios/{usuario_id}")
def api_atualizar_usuario(
    usuario_id: int,
    req: UsuarioIn,
    admin: Usuario = Depends(auth.exigir_admin),
    repo: RepositorioUsuarios = Depends(auth.repositorio_usuarios),
):
    motivo = _validar_usuario_in(req)
    if motivo:
        return _erro(ValueError(motivo))
    atual = repo.obter(usuario_id)
    if atual is None:
        return _erro(LookupError("Usuario nao encontrado."), 404)
    if (
        atual.perfil == "ADMIN" and req.perfil != "ADMIN" and atual.ativo
        and repo.quantidade_admins_ativos() <= 1
    ):  # fmt: skip
        return _erro(ValueError("Nao e possivel rebaixar o unico administrador ativo."))
    try:
        novo = repo.atualizar(usuario_id, req.nome, req.email, req.perfil)
    except UsuarioInvalido as exc:
        return _erro(exc, 409)
    if atual.perfil != novo.perfil:
        repo.encerrar_sessoes_do_usuario(usuario_id)  # perfil novo vale no proximo login
    auth.registrar_evento("usuario_atualizado", por=admin.id, usuario_id=usuario_id)
    return novo.publico()


class AtivoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ativo: bool


@app.post("/api/usuarios/{usuario_id}/ativo")
def api_ativar_usuario(
    usuario_id: int,
    req: AtivoIn,
    admin: Usuario = Depends(auth.exigir_admin),
    repo: RepositorioUsuarios = Depends(auth.repositorio_usuarios),
):
    """Cancelar = desativar (Sinistros); derruba as sessoes na hora."""
    alvo = repo.obter(usuario_id)
    if alvo is None:
        return _erro(LookupError("Usuario nao encontrado."), 404)
    if not req.ativo:
        if alvo.id == admin.id:
            return _erro(ValueError("Voce nao pode desativar o proprio usuario."))
        if alvo.admin and alvo.ativo and repo.quantidade_admins_ativos() <= 1:
            return _erro(ValueError("Nao e possivel desativar o unico administrador ativo."))
    repo.definir_ativo(usuario_id, req.ativo)
    auth.registrar_evento("usuario_ativo", por=admin.id, usuario_id=usuario_id, ativo=req.ativo)
    return repo.obter(usuario_id).publico()  # type: ignore[union-attr]


@app.post("/api/usuarios/{usuario_id}/resetar-senha")
def api_resetar_senha(
    usuario_id: int,
    admin: Usuario = Depends(auth.exigir_admin),
    repo: RepositorioUsuarios = Depends(auth.repositorio_usuarios),
):
    """Senha temporaria nova, mostrada uma vez; sessoes do usuario encerradas."""
    alvo = repo.obter(usuario_id)
    if alvo is None:
        return _erro(LookupError("Usuario nao encontrado."), 404)
    if alvo.id == admin.id:
        return _erro(ValueError("Para a propria senha use 'Trocar senha'."))
    temporaria = auth.senha_temporaria()
    repo.definir_senha(usuario_id, auth.gerar_hash(temporaria), trocar_senha=True)
    auth.registrar_evento("senha_resetada", por=admin.id, usuario_id=usuario_id)
    return {"ok": True, "senha_temporaria": temporaria}


# ------------------------------------------------ ADR-09: chaves da API do portal
class ChaveApiIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nome: str = Field(..., min_length=2, max_length=120)
    administradoras: list[str] = Field(default_factory=list)
    todas: bool = False
    ips: list[str] = Field(default_factory=list)


@app.get("/api/chaves")
def api_listar_chaves(
    _: Usuario = Depends(auth.exigir_admin),
    repo: RepositorioChaves = Depends(auth.repositorio_chaves),
):
    return [c.publico() for c in repo.listar()]


@app.post("/api/chaves", status_code=201)
def api_criar_chave(
    req: ChaveApiIn,
    admin: Usuario = Depends(auth.exigir_admin),
    repo: RepositorioChaves = Depends(auth.repositorio_chaves),
):
    """Cria a chave e mostra o texto UMA vez ao administrador; o banco guarda so o hash."""
    try:
        nova, texto = repo.criar(
            req.nome, req.administradoras, todas=req.todas, ips=req.ips, criada_por=admin.id
        )
    except ChaveInvalida as exc:
        return _erro(exc)
    auth.registrar_evento("chave_api_criada", por=admin.id, chave_id=nova.id, prefixo=nova.prefixo)
    return JSONResponse({**nova.publico(), "chave": texto}, status_code=201)


@app.put("/api/chaves/{chave_id}")
def api_atualizar_chave(
    chave_id: int,
    req: ChaveApiIn,
    admin: Usuario = Depends(auth.exigir_admin),
    repo: RepositorioChaves = Depends(auth.repositorio_chaves),
):
    if repo.obter(chave_id) is None:
        return _erro(LookupError("Chave nao encontrada."), 404)
    try:
        nova = repo.atualizar(chave_id, req.nome, req.administradoras, todas=req.todas, ips=req.ips)
    except ChaveInvalida as exc:
        return _erro(exc)
    auth.registrar_evento("chave_api_atualizada", por=admin.id, chave_id=chave_id)
    return nova.publico()


@app.post("/api/chaves/{chave_id}/revogar")
def api_revogar_chave(
    chave_id: int,
    admin: Usuario = Depends(auth.exigir_admin),
    repo: RepositorioChaves = Depends(auth.repositorio_chaves),
):
    """Irreversivel: a chave deixa de autenticar na hora (GAP-24 fechado)."""
    alvo = repo.obter(chave_id)
    if alvo is None:
        return _erro(LookupError("Chave nao encontrada."), 404)
    repo.revogar(chave_id)
    auth.registrar_evento(
        "chave_api_revogada", por=admin.id, chave_id=chave_id, prefixo=alvo.prefixo
    )
    return repo.obter(chave_id).publico()  # type: ignore[union-attr]


# ---------------------------------------------------------------- API cascata
def _erro(exc: Exception, status: int = 400) -> JSONResponse:
    return JSONResponse({"erro": str(exc), "tipo": type(exc).__name__}, status_code=status)


@app.get("/api/incendio/administradoras")
def api_administradoras(repo: RepositorioCertificados = Depends(get_repositorio)):
    """QRY-01 — value = codigo, texto = nome (RF-03)."""
    return [
        {"codigo": a.codigo, "nome": a.nome, "abrev": a.abreviacao_normalizada,
         "possui_portal": a.possui_portal}
        for a in Cascata(repo).administradoras()
    ]  # fmt: skip


@app.get("/api/incendio/apolices")
def api_apolices(
    administradora: str = Query(""),
    inicio_vig: date | None = Query(None),
    data_fat: date | None = Query(None),
    repo: RepositorioCertificados = Depends(get_repositorio),
):
    """QRY-03 — rotulo RN-08, chave estruturada RN-17. data_fat: RN-05a (Emissao:)."""
    try:
        refs = Cascata(repo).apolices(administradora, inicio_vig, data_fat)
    except ValueError as exc:
        return _erro(exc)
    return [{"apolice": r.apolice, "seq": r.seq, "rotulo": rotulo_apolice(r)} for r in refs]


@app.get("/api/incendio/faturas")
def api_faturas(
    administradora: str,
    apolice: str,
    seq: int,
    inicio_vig: date | None = Query(None),
    data_fat: date | None = Query(None),
    repo: RepositorioCertificados = Depends(get_repositorio),
):
    """QRY-04. data_fat: RN-05a — data de emissao da fatura (faturas.data_fat)."""
    try:
        return Cascata(repo).faturas(administradora, apolice, seq, inicio_vig, data_fat)
    except ValueError as exc:
        return _erro(exc)


@app.get("/api/incendio/segurados")
def api_segurados(
    administradora: str,
    apolice: str,
    seq: int,
    fatura: int,
    repo: RepositorioCertificados = Depends(get_repositorio),
):
    """QRY-05 — lista completa (RD-24); RF-13 derivados vem no payload."""
    lote = ChaveLote(administradora, apolice, seq, fatura)
    try:
        itens = Cascata(repo).segurados(lote)
    except ProdutoIndeterminado as exc:
        return _erro(exc, 422)
    return {
        "lote": {"administradora": administradora, "apolice": apolice, "seq": seq,
                 "fatura": fatura},  # fmt: skip
        "quantidade": len(itens),
        "produto": itens[0].produto_curto if itens else None,
        "faz_tudo_lar": itens[0].faz_tudo_lar if itens else False,
        "locacao": itens[0].locacao if itens else False,
        "segurados": [i.__dict__ for i in itens],
    }


# ---------------------------------------------------------------- API emissao
class ChaveIn(BaseModel):
    administradora: str
    apolice: str
    seq: int
    fatura: int
    certificado: str
    cpf_cnpj: str

    def dominio(self) -> ChaveCertificado:
        return ChaveCertificado(**self.model_dump())


class EmissaoIn(BaseModel):
    # Campo desconhecido e erro 422: um servidor antigo ainda em memoria nao pode ignorar em
    # silencio uma opcao nova da tela (aconteceu com upload_aws em 15/09/2026).
    model_config = ConfigDict(extra="forbid")

    administradora: str
    apolice: str
    seq: int
    fatura: int
    pasta: str = Field(..., description="pasta de destino (DirectoryEdit1)")
    selecionados: list[ChaveIn] | None = Field(None, description="None = todos (RF-14)")
    imprime_premio: bool = False  # CheckBox1 — RF-10
    faz_tudo_lar: bool | None = None  # CheckBox4 — ADR-06: escolha do operador; None = RN-18
    individuais: bool = True  # CheckBox2 — RF-07
    json_unico: bool = False  # RD-26 — um JSON do lote (chave cpf|certificado), PDFs individuais
    so_xml: bool = False  # CheckBox6 'So XML de Cert.' — aqui: so JSON, sem PDF
    competencia: date | None = None  # RN-19
    upload_aws: bool = False  # CheckBox3 — RF-21 (DEF-07 corrigido: agora tem efeito)
    # Versao do JS que montou o pedido; diferente da do servidor => tela desatualizada (409)
    versao_tela: str | None = None


@app.post("/api/incendio/emitir")
def api_emitir(
    req: EmissaoIn,
    request: Request,
    repo: RepositorioCertificados = Depends(get_repositorio),
    fabrica_publicacao: FabricaPublicacao = Depends(get_fabrica_publicacao),
):
    """UC-01/02/03/04 — o mesmo caso de uso da CLI (RF-11). RF-21: Upload AWS opcional."""
    if req.versao_tela != __version__:
        return _erro(
            RuntimeError(
                f"Tela desatualizada (JS {req.versao_tela or 'sem versao'}, servidor "
                f"{__version__}): recarregue a pagina com Ctrl+F5 e repita a emissao"
            ),
            409,
        )
    pasta = Path(req.pasta)
    try:
        validar_pasta_destino(pasta)  # RF-06
    except NomeArquivoInvalido as exc:
        return _erro(exc)
    if req.upload_aws and req.so_xml:
        return _erro(ValueError("Upload AWS exige o PDF: desmarque 'So XML de Cert.' (RF-21)"))
    publicador, registro = fabrica_publicacao() if req.upload_aws else (None, None)

    lote = ChaveLote(req.administradora, req.apolice, req.seq, req.fatura)
    opcoes = OpcoesEmissao(
        pasta_saida=pasta,
        exibe_premio=req.imprime_premio,
        faz_tudo_lar=req.faz_tudo_lar,
        individuais=req.individuais,
        json_unico=req.json_unico,
        data_competencia=req.competencia,
        apenas=[c.dominio() for c in req.selecionados] if req.selecionados is not None else None,
        modo_conexao="firebird-local",
    )
    if req.so_xml:
        return emitir_lote(repo, lote, opcoes).para_dict()
    cfg = _config()

    from certgen.render.html import DadosRender
    from certgen.render.pdf import ErroRenderizacao, RenderizadorPdf

    try:
        with RenderizadorPdf() as render:

            def renderizar(cert, meta, destino):
                dados = DadosRender(meta.gerado_em.date(), meta.exibe_premio, meta.faz_tudo_lar)
                return render.renderizar_certificado(cert, dados, destino)

            resultado = emitir_lote(
                repo,
                lote,
                opcoes,
                renderizar_pdf=renderizar,
                publicador=publicador,
                registro=registro,
            ).para_dict()
    except ErroRenderizacao as exc:
        return _erro(exc, 503)
    if publicador is not None:  # ADR-09: bucket privado; o operador abre pelo link assinado
        for item in resultado["emitidos"]:
            item["link_temporario"] = _link_temporario(publicador, item.get("link"), cfg)
    return resultado


def _link_temporario(publicador: PublicadorArquivos, link: str | None, cfg: Config) -> str | None:
    if not link:
        return None
    try:
        return publicador.link_temporario(link, cfg.link_validade_seg)
    except Exception as exc:  # o relatorio nao falha por causa do link assinado
        log.warning("link assinado indisponivel para %s: %s", link, exc)
        return None


# ------------------------------------------------------- RF-06a: baixar arquivos
EXTENSOES_BAIXAVEIS = frozenset({".pdf", ".json"})


def _arquivo_permitido(caminho: str, cfg: Config) -> Path:
    """RF-06a — so arquivos .pdf/.json dentro da pasta de saida do servidor. Qualquer
    tentativa de sair dela (.., links, outra raiz) e recusada antes de tocar o disco."""
    raiz = cfg.pasta_saida.resolve()
    alvo = Path(caminho).expanduser().resolve()
    if alvo.suffix.lower() not in EXTENSOES_BAIXAVEIS or not alvo.is_relative_to(raiz):
        raise NomeArquivoInvalido(
            "arquivo fora da pasta de saida do servidor ou tipo nao permitido"
        )
    if not alvo.is_file():
        raise NomeArquivoInvalido("arquivo nao encontrado")
    return alvo


@app.get("/api/incendio/arquivo")
def api_baixar_arquivo(
    caminho: str = Query(..., description="caminho devolvido pelo relatorio da emissao"),
    cfg: Config = Depends(get_config),
    usuario: Usuario = Depends(auth.usuario_atual),
):
    """RF-06a (homologacao 29/10/2026) — entrega ao navegador um PDF/JSON emitido, para o
    operador salvar na propria maquina quando a tela roda num servidor (Render)."""
    from fastapi.responses import FileResponse

    try:
        alvo = _arquivo_permitido(caminho, cfg)
    except NomeArquivoInvalido as exc:
        return _erro(exc, 404)
    auth.registrar_evento("arquivo_baixado", usuario_id=usuario.id, arquivo=alvo.name)
    tipo = "application/pdf" if alvo.suffix.lower() == ".pdf" else "application/json"
    return FileResponse(str(alvo), media_type=tipo, filename=alvo.name)


class ZipIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    arquivos: list[str] = Field(..., min_length=1, max_length=2000)
    nome: str = Field("certificados", max_length=80)


@app.post("/api/incendio/zip")
def api_baixar_zip(
    req: ZipIn,
    cfg: Config = Depends(get_config),
    usuario: Usuario = Depends(auth.usuario_atual),
):
    """RF-06a — um .zip com os arquivos do relatorio (mesma regra de pasta do download
    individual). Montado em memoria: um lote tem dezenas de PDFs de ~250 KB."""
    import io
    import re
    import zipfile

    from fastapi.responses import StreamingResponse

    try:
        alvos = [_arquivo_permitido(c, cfg) for c in req.arquivos]
    except NomeArquivoInvalido as exc:
        return _erro(exc, 404)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for alvo in alvos:
            z.write(alvo, alvo.name)
    buf.seek(0)
    nome = re.sub(r"[^A-Za-z0-9_.-]", "_", req.nome) or "certificados"
    auth.registrar_evento("zip_baixado", usuario_id=usuario.id, quantidade=len(alvos))
    return StreamingResponse(
        buf, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{nome}.zip"'},
    )  # fmt: skip


# ------------------------------------------------------------ escolha de pasta
def _dialogo_pasta(inicial: str | None) -> str | None:
    """Abre a janela nativa do Windows para escolher pasta. O servidor roda na mesma
    maquina do operador (RNF-10), entao o dialogo aparece na tela dele. Devolve None
    se cancelado."""
    import tkinter
    from tkinter import filedialog

    raiz = tkinter.Tk()
    raiz.withdraw()
    raiz.attributes("-topmost", True)
    try:
        escolhida = filedialog.askdirectory(
            title="Pasta de destino dos certificados",
            initialdir=inicial if inicial and Path(inicial).is_dir() else None,
            mustexist=True,
        )
    finally:
        raiz.destroy()
    return str(Path(escolhida)) if escolhida else None


app.state.escolher_pasta = _dialogo_pasta  # testes substituem


class PastaIn(BaseModel):
    inicial: str | None = None


@app.post("/api/escolher-pasta")
def api_escolher_pasta(req: PastaIn, request: Request, local: bool = Depends(cliente_local)):
    if not local:
        return _erro(
            PermissionError("o dialogo de pastas abre na maquina do servidor; digite o caminho"),
            403,
        )
    try:
        pasta = request.app.state.escolher_pasta(req.inicial)
    except Exception as exc:  # tkinter indisponivel, sem sessao grafica etc.
        return _erro(exc, 501)
    return {"pasta": pasta}


@app.get("/api/saude")
def saude() -> dict:
    return {"ok": True, "versao": __version__}


def _encerrar_processo() -> None:
    """Botao Sair do menu: encerra o servidor com o mesmo efeito de Ctrl+C (uvicorn desliga
    graciosamente). Roda meio segundo depois para a resposta chegar ao navegador."""
    import signal
    import threading

    threading.Timer(0.5, lambda: signal.raise_signal(signal.SIGINT)).start()


app.state.encerrar = _encerrar_processo  # testes substituem por um espiao


@app.post("/api/encerrar")
def api_encerrar(request: Request, local: bool = Depends(cliente_local)):
    if not local:
        return _erro(PermissionError("so o operador da maquina do servidor pode encerrar"), 403)
    request.app.state.encerrar()
    return {"ok": True, "mensagem": "encerrando"}
