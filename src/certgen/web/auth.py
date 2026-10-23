"""Autenticacao da tela — ADR-08 (decisao do usuario, 23/10/2026).

Politicas copiadas do Sistema de Sinistros FedCorp (`src/auth.js`, `src/routes/auth.js`,
`src/server.js`), traduzidas para FastAPI:

- senha: minimo 8 caracteres, letras e numeros, sem um unico caractere repetido;
  hash bcrypt (custo 12); senha temporaria gerada sem caracteres ambiguos;
- login: e-mail + senha; 10 falhas por e-mail+IP em 15 min bloqueiam (so falhas contam);
  comparacao contra um hash falso quando o e-mail nao existe (tempo de resposta igual);
  mensagem de erro unica ("E-mail ou senha invalidos");
- sessao: cookie `certgen_sessao` httpOnly, SameSite=Lax, Secure quando a pagina chega
  por HTTPS, 8 horas; token aleatorio guardado como SHA-256 no SQLite (usuarios.py);
- CSRF: toda chamada que altera dados exige o header `X-Requested-With: fetch` e, quando
  o navegador envia `Origin`, ele tem de ser o proprio host;
- cabecalhos: CSP so 'self', nosniff, frame-ancestors 'none', Referrer-Policy, HSTS em HTTPS.

Nada disto toca o dominio (ADR-01). A API do portal (`/v1/*`) continua autenticada
pela chave RN-30 e NAO passa pela sessao.
"""

from __future__ import annotations

import hmac
import logging
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from starlette.responses import Response as StarletteResponse

from certgen.web.usuarios import RepositorioUsuarios, Usuario

log = logging.getLogger("certgen.web.auth")

COOKIE_SESSAO = "certgen_sessao"
HORAS_SESSAO = 8
RONDAS_BCRYPT = 12  # testes baixam para 4
SENHA_MIN, SENHA_MAX = 8, 72  # 72: limite do bcrypt

# Caminhos que nao exigem sessao. /v1/* e a API do portal (chave RN-30, modo combinado).
CAMINHOS_PUBLICOS = frozenset({"/login", "/api/auth/login", "/api/saude"})
PREFIXOS_PUBLICOS = ("/static/", "/v1/")
# Com senha temporaria pendente, so isto e permitido alem do /login (Sinistros: trocar_senha).
CAMINHOS_TROCA_PENDENTE = frozenset(
    {"/trocar-senha", "/api/auth/trocar-senha", "/api/auth/logout", "/api/auth/me"}
)
METODOS_QUE_ALTERAM = frozenset({"POST", "PUT", "PATCH", "DELETE"})

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


# ------------------------------------------------------------------- senhas
def validar_senha(senha: object) -> str | None:
    """Mensagem de erro ou None. Politica do Sinistros com minimo elevado para 8."""
    if not isinstance(senha, str) or len(senha) < SENHA_MIN:
        return f"A senha deve ter no minimo {SENHA_MIN} caracteres."
    if len(senha.encode()) > SENHA_MAX:
        return f"A senha deve ter no maximo {SENHA_MAX} caracteres."
    if not re.search(r"[A-Za-zÀ-ÿ]", senha) or not re.search(r"\d", senha):
        return "A senha deve conter letras e numeros."
    if len(set(senha)) == 1:
        return "A senha nao pode ser um unico caractere repetido."
    return None


def senha_temporaria() -> str:
    """12 caracteres, letras + numeros, sem 0/O/1/l/I (Sinistros: `senhaTemporaria`)."""
    letras = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ"
    numeros = "23456789"
    todos = letras + numeros
    chars = [secrets.choice(letras), secrets.choice(numeros)]
    chars += [secrets.choice(todos) for _ in range(10)]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def gerar_hash(senha: str) -> str:
    import bcrypt

    return bcrypt.hashpw(senha.encode(), bcrypt.gensalt(RONDAS_BCRYPT)).decode()


def conferir_senha(senha: str, senha_hash: str | None) -> bool:
    """Compara sempre contra um hash (falso quando o usuario nao existe), para o tempo
    de resposta nao revelar quais e-mails estao cadastrados."""
    import bcrypt

    alvo = senha_hash or _hash_falso()
    try:
        return bcrypt.checkpw(senha.encode()[:SENHA_MAX], alvo.encode()) and senha_hash is not None
    except ValueError:
        return False


_HASH_FALSO: str | None = None


def _hash_falso() -> str:
    global _HASH_FALSO
    if _HASH_FALSO is None:
        _HASH_FALSO = gerar_hash("senha-inexistente-0")
    return _HASH_FALSO


# ------------------------------------------------------- limite de tentativas
class LimiteTentativas:
    """Janela deslizante em memoria: `maximo` falhas por chave em `janela_seg` segundos.
    So falhas contam (Sinistros: `skipSuccessfulRequests`)."""

    def __init__(self, maximo: int = 10, janela_seg: int = 15 * 60) -> None:
        self.maximo, self.janela = maximo, janela_seg
        self._falhas: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _podar(self, chave: str, agora: float) -> deque[float]:
        fila = self._falhas[chave]
        while fila and fila[0] <= agora - self.janela:
            fila.popleft()
        return fila

    def bloqueado(self, chave: str) -> int:
        """0 se liberado; senao, segundos ate liberar."""
        with self._lock:
            fila = self._podar(chave, time.monotonic())
            if len(fila) < self.maximo:
                return 0
            return max(1, int(fila[0] + self.janela - time.monotonic()))

    def registrar_falha(self, chave: str) -> None:
        with self._lock:
            self._podar(chave, time.monotonic()).append(time.monotonic())

    def limpar(self, chave: str) -> None:
        with self._lock:
            self._falhas.pop(chave, None)

    def limpar_tudo(self) -> None:
        with self._lock:
            self._falhas.clear()


limite_login = LimiteTentativas(maximo=10, janela_seg=15 * 60)  # por e-mail + IP
limite_login_ip = LimiteTentativas(maximo=30, janela_seg=15 * 60)  # por IP, qualquer e-mail


def ip_de(request: Request) -> str:
    return request.client.host if request.client else "?"


# ------------------------------------------------------------- requisicao
def repositorio_usuarios(request: Request) -> RepositorioUsuarios:
    repo = getattr(request.app.state, "usuarios", None)
    if repo is None:
        raise HTTPException(503, "cadastro de usuarios indisponivel")
    return repo


def usuario_atual(request: Request) -> Usuario:
    """Dependencia: o middleware ja resolveu a sessao em request.state.usuario."""
    usuario = getattr(request.state, "usuario", None)
    if usuario is None:
        raise HTTPException(401, "Sessao expirada. Faca login novamente.")
    return usuario


def exigir_admin(request: Request) -> Usuario:
    usuario = usuario_atual(request)
    if not usuario.admin:
        raise HTTPException(403, "Acesso restrito ao Administrador do Sistema.")
    return usuario


def caminho_publico(caminho: str) -> bool:
    return caminho in CAMINHOS_PUBLICOS or caminho.startswith(PREFIXOS_PUBLICOS)


def _csrf_invalido(request: Request) -> str | None:
    """CSRF do Sinistros: header obrigatorio + Origin igual ao host (quando enviado)."""
    if request.headers.get("X-Requested-With") != "fetch":
        return "Requisicao invalida (falta X-Requested-With)."
    origem = request.headers.get("origin")
    if origem:
        host_origem = urlsplit(origem).netloc
        if not hmac.compare_digest(host_origem, request.headers.get("host", "")):
            return "Requisicao de origem desconhecida."
    return None


def cookie_seguro(request: Request) -> bool:
    """Secure quando a pagina chegou por HTTPS (Render: X-Forwarded-Proto via proxy_headers)."""
    return request.url.scheme == "https"


def gravar_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        COOKIE_SESSAO,
        token,
        max_age=HORAS_SESSAO * 3600,
        httponly=True,
        samesite="lax",
        secure=cookie_seguro(request),
        path="/",
    )


def apagar_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(COOKIE_SESSAO, path="/", httponly=True, samesite="lax",
                           secure=cookie_seguro(request))  # fmt: skip


def aplicar_cabecalhos_seguranca(request: Request, response: StarletteResponse) -> None:
    h = response.headers
    h.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; font-src 'self'; frame-ancestors 'none'; form-action 'self'; "
        "base-uri 'self'; object-src 'none'",
    )
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Referrer-Policy", "same-origin")
    h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.url.scheme == "https":
        h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.url.path.startswith("/api/") or request.url.path.startswith("/v1/"):
        h.setdefault("Cache-Control", "no-store")


async def middleware_sessao(request: Request, call_next):
    """Resolve a sessao, aplica CSRF e exige login fora dos caminhos publicos.

    Paginas sem sessao -> 302 para /login?next=...; chamadas /api/* -> 401 JSON.
    Senha temporaria pendente -> so /trocar-senha (paginas 302, API 403).
    """
    caminho = request.url.path
    repo = getattr(request.app.state, "usuarios", None)
    token = request.cookies.get(COOKIE_SESSAO)
    usuario = repo.usuario_da_sessao(token) if repo is not None else None
    request.state.usuario = usuario
    request.state.token_sessao = token if usuario else None

    publico = caminho_publico(caminho)
    api = caminho.startswith("/api/")

    if request.method in METODOS_QUE_ALTERAM and not caminho.startswith("/v1/"):
        motivo = _csrf_invalido(request)
        if motivo:
            resposta: StarletteResponse = JSONResponse({"erro": motivo}, status_code=403)
            aplicar_cabecalhos_seguranca(request, resposta)
            return resposta

    if not publico:
        if usuario is None:
            if api:
                resposta = JSONResponse(
                    {"erro": "Sessao expirada. Faca login novamente."}, status_code=401
                )
            else:
                destino = "/login"
                if caminho != "/" and request.method == "GET":
                    destino += f"?next={caminho}"
                resposta = RedirectResponse(destino, status_code=302)
            aplicar_cabecalhos_seguranca(request, resposta)
            return resposta
        if usuario.trocar_senha and caminho not in CAMINHOS_TROCA_PENDENTE:
            if api:
                resposta = JSONResponse(
                    {"erro": "Defina uma nova senha antes de continuar."}, status_code=403
                )
            else:
                resposta = RedirectResponse("/trocar-senha", status_code=302)
            aplicar_cabecalhos_seguranca(request, resposta)
            return resposta

    resposta = await call_next(request)
    aplicar_cabecalhos_seguranca(request, resposta)
    return resposta


def registrar_evento(evento: str, **dados: object) -> None:
    """Auditoria (RNF-13 aplicado a tela): nunca senha, nunca hash, nunca token."""
    import json

    log.info(json.dumps({"evento": evento, **dados}, ensure_ascii=False, default=str))
