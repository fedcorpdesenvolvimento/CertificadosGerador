"""Fase 8 — APIs para o portal (secao 11.1: RF-18, RF-19, RF-20, RN-30, RNF-10b, RNF-13).

Endpoints (todos sob /v1, autenticados por X-API-Key):
  GET  /v1/saude                   — RF-18: a chave funciona? devolve cliente e escopo
  GET  /v1/administradoras         — ADR-09: administradoras que a chave pode consultar
  POST /v1/segurados/verificar     — UC-13: {"existe", "quantidade", "certificados": [...]}
  POST /v1/certificados/emitir     — UC-12: emite, publica no S3, devolve link + JSON (RD-29)
  POST /v1/certificados/link       — ADR-09: link assinado de certificado ja emitido

ADR-09 (28/10/2026, retorno do integrador — GAP-23/24/26 fechados):
- chaves cadastradas no SQLite (web/chaves_api.py), uma por cliente integrador, com
  escopo de administradoras (403 fora dele) e IPs opcionais; CERTGEN_API_KEY continua
  aceita so como chave de transicao (todas as administradoras);
- limite de taxa por chave (429 + Retry-After) e bloqueio por IP de chaves erradas,
  reaproveitando o mecanismo da tela (web/auth.py);
- X-Request-Id aceito e devolvido em toda resposta (gerado quando ausente) e gravado
  no log RNF-13;
- envelope unico de erro: {"codigo", "mensagem", "request_id", "detalhes"};
- bucket privado: `link` e uma URL assinada com prazo (`link_expira_em`); o link
  permanente fica em `documento.arquivo.link` e no banco (RD-25, RD-28).

RNF-13: um registro de log JSON por chamada, sem chave e sem nome do segurado.
Endpoints sincronos (`def`): rodam no threadpool do Starlette, como na tela.
"""

from __future__ import annotations

import hmac
import json
import logging
import re
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from certgen import __version__
from certgen.application.emitir_certificados import OpcoesEmissao, RenderizadorPdf
from certgen.application.emitir_portal import (
    NenhumCertificado,
    PedidoInvalido,
    PedidoPortal,
    PedidoVerificacao,
    emitir_para_portal,
    links_para_portal,
    verificar_segurado,
)
from certgen.application.listar_cascata import Cascata
from certgen.application.ports import (
    ErroPublicacao,
    ErroRepositorio,
    PublicadorArquivos,
    RegistroLinks,
    RepositorioCertificados,
)
from certgen.config.settings import Config
from certgen.web import auth
from certgen.web.chaves_api import ChaveApi, RepositorioChaves

log = logging.getLogger("certgen.api")

HEADER_REQUEST_ID = "X-Request-Id"
_REQUEST_ID_OK = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


# ------------------------------------------------------------------ erros
class ErroApi(Exception):
    """ADR-09 — erro com envelope unico. `detalhes` e opcional e nunca leva dado pessoal
    alem do que o proprio pedido trouxe."""

    def __init__(
        self, status: int, codigo: str, mensagem: str, detalhes: dict | None = None,
        cabecalhos: dict[str, str] | None = None,
    ) -> None:  # fmt: skip
        super().__init__(mensagem)
        self.status, self.codigo, self.mensagem = status, codigo, mensagem
        self.detalhes, self.cabecalhos = detalhes, cabecalhos or {}


CODIGOS_HTTP = {
    400: "PEDIDO_INVALIDO",
    401: "CHAVE_INVALIDA",
    403: "ACESSO_NEGADO",
    404: "NAO_ENCONTRADO",
    405: "METODO_NAO_PERMITIDO",
    422: "CORPO_MALFORMADO",
    429: "LIMITE_EXCEDIDO",
    500: "ERRO_INTERNO",
    502: "PUBLICACAO_FALHOU",
    503: "SERVICO_INDISPONIVEL",
}


def request_id_de(request: Request) -> str:
    rid = getattr(request.state, "request_id", None)
    if not rid:
        rid = _novo_request_id(request.headers.get(HEADER_REQUEST_ID))
        request.state.request_id = rid
    return rid


def _novo_request_id(recebido: str | None) -> str:
    """Aceita o id do portal quando e seguro para log; senao gera um."""
    if recebido and _REQUEST_ID_OK.match(recebido):
        return recebido
    return uuid.uuid4().hex


def resposta_erro(
    request: Request, status: int, codigo: str, mensagem: str, detalhes: dict | None = None,
    cabecalhos: dict[str, str] | None = None,
) -> JSONResponse:  # fmt: skip
    rid = request_id_de(request)
    corpo = {"codigo": codigo, "mensagem": mensagem, "request_id": rid, "detalhes": detalhes}
    resposta = JSONResponse(corpo, status_code=status, headers=cabecalhos)
    resposta.headers[HEADER_REQUEST_ID] = rid
    return resposta


def _e_portal(request: Request) -> bool:
    return request.url.path.startswith("/v1/")


async def _tratar_erro_api(request: Request, exc: ErroApi):
    return resposta_erro(
        request, exc.status, exc.codigo, exc.mensagem, exc.detalhes, exc.cabecalhos
    )


async def _tratar_http(request: Request, exc: StarletteHTTPException):
    if not _e_portal(request):
        return await http_exception_handler(request, exc)
    codigo = CODIGOS_HTTP.get(exc.status_code, "ERRO")
    cabecalhos = dict(exc.headers or {})
    return resposta_erro(request, exc.status_code, codigo, str(exc.detail), None, cabecalhos)


async def _tratar_validacao(request: Request, exc: RequestValidationError):
    if not _e_portal(request):
        return await request_validation_exception_handler(request, exc)
    campos = [
        {"campo": ".".join(str(p) for p in e.get("loc", ()) if p != "body"), "erro": e.get("msg")}
        for e in exc.errors()
    ]
    return resposta_erro(
        request, 422, "CORPO_MALFORMADO", "corpo do pedido malformado", {"campos": campos}
    )


async def _tratar_inesperado(request: Request, exc: Exception):
    if not _e_portal(request):
        raise exc
    rid = request_id_de(request)
    log.exception(
        json.dumps({"evento": "erro_interno", "request_id": rid, "tipo": type(exc).__name__})
    )
    return resposta_erro(
        request, 500, "ERRO_INTERNO", "erro interno; informe o request_id a FedCorp"
    )


# --------------------------------------------------------------- dependencias
@lru_cache(maxsize=1)
def _config() -> Config:
    return Config.do_ambiente()


def get_config() -> Config:
    return _config()


def get_api_key() -> str:
    """RN-30 original — chave de transicao em CERTGEN_API_KEY ('' quando ausente)."""
    return _config().api_key


@lru_cache(maxsize=1)
def _chaves() -> RepositorioChaves:
    return RepositorioChaves(_config().usuarios_db)


def get_repositorio_chaves(request: Request) -> RepositorioChaves:
    """ADR-09 — cadastro de chaves no SQLite da tela. No modo combinado a tela ja abriu
    o repositorio (app.state.chaves); `certgen api` abre o seu a partir do ambiente."""
    repo = getattr(request.app.state, "chaves", None)
    return repo if repo is not None else _chaves()


CHAVE_TRANSICAO = ChaveApi(
    id=0, nome="CERTGEN_API_KEY (transicao)", prefixo="env", administradoras=(), todas=True,
    ips=(), ativa=True, criada_em="", criada_por=None, revogada_em=None, ultimo_uso=None,
    ultimo_ip=None,
)  # fmt: skip


def autenticar(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    transicao: str = Depends(get_api_key),
    chaves: RepositorioChaves = Depends(get_repositorio_chaves),
) -> ChaveApi:
    """RN-30 revisto (ADR-09): resolve a chave, aplica IP permitido e limite de taxa.
    Mensagens nao revelam se a chave existe, e a chave nunca aparece em log."""
    ip = auth.ip_de(request)
    request_id_de(request)
    bloqueio = auth.limite_api_chave_errada.bloqueado(ip)
    if bloqueio:
        raise ErroApi(
            429, "LIMITE_EXCEDIDO", "muitas tentativas com chave invalida; aguarde",
            cabecalhos={"Retry-After": str(bloqueio)},
        )  # fmt: skip
    chave: ChaveApi | None = None
    if x_api_key:
        if transicao and hmac.compare_digest(x_api_key.encode(), transicao.encode()):
            chave = CHAVE_TRANSICAO
        else:
            chave = chaves.autenticar(x_api_key)
    if chave is None:
        auth.limite_api_chave_errada.registrar_falha(ip)
        raise ErroApi(401, "CHAVE_INVALIDA", "chave de autenticacao ausente ou invalida")
    if not chave.permite_ip(ip):
        log.warning(json.dumps({"evento": "origem_negada", "chave": chave.prefixo, "ip": ip}))
        raise ErroApi(403, "ORIGEM_NAO_PERMITIDA", "origem nao autorizada para esta chave")
    espera = auth.limite_api_chave.consumir(f"chave:{chave.id}")
    if espera:
        raise ErroApi(
            429, "LIMITE_EXCEDIDO",
            f"limite de {auth.limite_api_chave.maximo} chamadas por minuto excedido",
            cabecalhos={"Retry-After": str(espera)},
        )  # fmt: skip
    if chave.id:
        chaves.registrar_uso(chave.id, ip)
    request.state.chave_api = chave
    return chave


def exigir_administradora(chave: ChaveApi, administradora: str) -> None:
    """ADR-09 — escopo da chave: administradora fora da lista e 403."""
    if not chave.permite_administradora(administradora):
        raise ErroApi(
            403, "ADMINISTRADORA_NAO_PERMITIDA",
            "esta chave nao tem acesso a administradora informada",
            {"administradora": administradora.strip()},
        )  # fmt: skip


def get_repositorio() -> RepositorioCertificados:
    cfg = _config()
    if cfg.repositorio == "firebird":
        from certgen.adapters.firebird.repositorio import RepositorioFirebird

        return RepositorioFirebird(susep_corretora=cfg.susep_corretora)
    raise HTTPException(501, f"adaptador '{cfg.repositorio}' ainda nao implementado (Fase 5)")


def get_registro() -> RegistroLinks:
    """RD-20a — hoje a mesma classe do repositorio Firebird implementa a escrita."""
    cfg = _config()
    if cfg.repositorio == "firebird":
        from certgen.adapters.firebird.repositorio import RepositorioFirebird

        return RepositorioFirebird(susep_corretora=cfg.susep_corretora)
    raise HTTPException(501, "registro de links so existe no adaptador Firebird")


def get_publicador() -> PublicadorArquivos:
    from certgen.adapters.s3.publicador import PublicadorS3

    cfg = _config()
    return PublicadorS3(bucket=cfg.aws_bucket, regiao=cfg.aws_region)


@contextmanager
def _render_playwright() -> Iterator[RenderizadorPdf]:
    """Renderizador real (ADR-02). Um Chromium por chamada, como na tela."""
    from certgen.render.html import DadosRender
    from certgen.render.pdf import RenderizadorPdf as Motor

    with Motor() as motor:

        def renderizar(cert, meta, destino):
            dados = DadosRender(meta.gerado_em.date(), meta.exibe_premio, meta.faz_tudo_lar)
            return motor.renderizar_certificado(cert, dados, destino)

        yield renderizar


FabricaRender = Callable[[], AbstractContextManager[RenderizadorPdf]]


def get_fabrica_render() -> FabricaRender:
    """Testes sobrescrevem para nao depender do Chromium."""
    return _render_playwright


# ------------------------------------------------------------------- modelos
class PedidoIn(BaseModel):
    administradora: str = Field(..., examples=["0000001192"], description="pessoas.pessoa")
    cpf_cnpj: str = Field(
        ..., examples=["330.163.307-25"], description="CPF ou CNPJ; pontuacao aceita"
    )
    vigencia: date = Field(
        ..., examples=["2026-10-01"], description="= inicio_vig (RN-31), ISO 8601"
    )
    fatura: int | None = Field(
        None, examples=[382196], description="RD-31 — opcional; vem da verificacao"
    )
    certificado: str | None = Field(
        None, examples=["CF1DI/AP.602"], description="RD-31 — opcional; vem da verificacao"
    )


class VerificacaoIn(BaseModel):
    """RF-20 — sem vigencia: 'e segurado desta administradora?' + 3 vigencias (RN-35a)."""

    administradora: str = Field(..., examples=["0000001192"], description="pessoas.pessoa")
    cpf_cnpj: str = Field(
        ..., examples=["330.163.307-25"], description="CPF ou CNPJ; pontuacao aceita"
    )


# ------------------------------------------------------------------ endpoints
# As rotas vivem num APIRouter para que `certgen servidor` (combinado.py) as inclua na
# tela, no mesmo processo, sem duplicar logica (RF-11, RNF-08).
router = APIRouter()


def _ok(request: Request, corpo: dict, status: int = 200) -> JSONResponse:
    resposta = JSONResponse(corpo, status_code=status)
    resposta.headers[HEADER_REQUEST_ID] = request_id_de(request)
    return resposta


def _escopo(chave: ChaveApi) -> dict:
    return {"cliente": chave.nome, "chave": chave.prefixo,
            "administradoras": "todas" if chave.todas else list(chave.administradoras)}  # fmt: skip


@router.get("/v1/saude")
def saude(request: Request, chave: ChaveApi = Depends(autenticar)):
    """RF-18 — o portal testa a chave aqui e ve o escopo dela (ADR-09)."""
    return _ok(request, {"ok": True, "versao": __version__, **_escopo(chave)})


@router.get("/v1/administradoras")
def administradoras(
    request: Request,
    chave: ChaveApi = Depends(autenticar),
    repo: RepositorioCertificados = Depends(get_repositorio),
):
    """ADR-09 — codigo e nome das administradoras que esta chave pode consultar (QRY-01)."""
    todas = _capturar_banco(lambda: Cascata(repo).administradoras())
    itens = [
        {"codigo": a.codigo, "nome": a.nome, "abreviacao": a.abreviacao,
         "possui_portal": a.possui_portal}  # fmt: skip
        for a in todas
        if chave.permite_administradora(a.codigo)
    ]
    return _ok(request, {"quantidade": len(itens), "administradoras": itens})


@router.post(
    "/v1/segurados/verificar",
    responses={400: {"description": "administradora vazia ou documento sem 11/14 digitos"}},
)
def verificar(
    req: VerificacaoIn,
    request: Request,
    chave: ChaveApi = Depends(autenticar),
    repo: RepositorioCertificados = Depends(get_repositorio),
):
    """UC-13 / RF-20 — {"existe", "quantidade", "certificados": [RD-30...]}.

    existe = qualquer linha nao cancelada (RN-35); certificados = as 3 vigencias mais
    recentes (RN-35a) com nome, endereco, vigencia, apolice, seq, fatura, certificado e
    produto, para o portal chamar /v1/certificados/emitir apontando fatura e certificado.
    Nao e prova de identidade: o portal autentica o segurado por conta propria (ADR-09).
    """
    inicio = time.monotonic()
    pedido = _pedido_verificacao(req)
    exigir_administradora(chave, pedido.administradora)
    resposta = _capturar_banco(lambda: verificar_segurado(repo, pedido))
    log.info(  # RNF-13: sem chave, sem nome, sem endereco — so as chaves
        json.dumps(
            {
                "evento": "verificacao_portal",
                "request_id": request_id_de(request),
                "chave": chave.prefixo,
                "ip": auth.ip_de(request),
                "pedido": pedido.para_dict(),
                "existe": resposta.existe,
                "vigencias": [
                    {
                        "inicio_vig": v.inicio_vig.isoformat() if v.inicio_vig else None,
                        "fatura": v.fatura,
                        "certificado": v.certificado,
                    }
                    for v in resposta.vigencias
                ],
                "http": 200,
                "duracao_ms": round((time.monotonic() - inicio) * 1000),
            },
            ensure_ascii=False,
        )
    )
    return _ok(request, resposta.para_dict())


@router.post("/v1/certificados/emitir")
def emitir(
    req: PedidoIn,
    request: Request,
    chave: ChaveApi = Depends(autenticar),
    repo: RepositorioCertificados = Depends(get_repositorio),
    publicador: PublicadorArquivos = Depends(get_publicador),
    registro: RegistroLinks = Depends(get_registro),
    cfg: Config = Depends(get_config),
    fabrica_render: FabricaRender = Depends(get_fabrica_render),
):
    """UC-12 / RF-18. 200 com ao menos um link; 404 sem certificado; 502 todos falharam.
    `link` e assinado e expira (`link_expira_em`); `documento.arquivo.link` e o permanente."""
    inicio = time.monotonic()
    pedido = _pedido_emissao(req)
    exigir_administradora(chave, pedido.administradora)

    opcoes = OpcoesEmissao(pasta_saida=cfg.pasta_saida, modo_conexao="firebird-local")  # RN-34
    from certgen.render.pdf import ErroRenderizacao

    try:
        with fabrica_render() as renderizar:
            resposta = _capturar_banco(
                lambda: emitir_para_portal(repo, publicador, registro, pedido, opcoes, renderizar)
            )
    except NenhumCertificado as exc:
        _registrar_log(request, chave, pedido, [], inicio, http=404)
        raise ErroApi(
            404, "CERTIFICADO_NAO_ENCONTRADO", str(exc), {"pedido": pedido.para_dict()}
        ) from exc
    except ErroRenderizacao as exc:
        _registrar_log(request, chave, pedido, [], inicio, http=503)
        raise ErroApi(
            503, "GERADOR_INDISPONIVEL", str(exc), {"pedido": pedido.para_dict()}
        ) from exc

    corpo = resposta.para_dict()
    for item in corpo["certificados"]:
        _assinar_item(item, publicador, cfg.link_validade_seg)
    status = 200 if resposta.algum_link else 502
    _registrar_log(request, chave, pedido, resposta.certificados, inicio, http=status)
    if status == 502:
        raise ErroApi(
            502, "PUBLICACAO_FALHOU",
            "nenhum certificado foi publicado; veja o motivo de cada item", corpo,
        )  # fmt: skip
    return _ok(request, corpo)


@router.post("/v1/certificados/link")
def link(
    req: PedidoIn,
    request: Request,
    chave: ChaveApi = Depends(autenticar),
    repo: RepositorioCertificados = Depends(get_repositorio),
    publicador: PublicadorArquivos = Depends(get_publicador),
    cfg: Config = Depends(get_config),
):
    """ADR-09 — link assinado novo para certificado JA emitido, sem reemitir. Mesmo corpo
    da emissao. Item `nao_emitido` quando a linha nunca recebeu link."""
    inicio = time.monotonic()
    pedido = _pedido_emissao(req)
    exigir_administradora(chave, pedido.administradora)
    try:
        itens = _capturar_banco(lambda: links_para_portal(repo, pedido))
    except NenhumCertificado as exc:
        raise ErroApi(
            404, "CERTIFICADO_NAO_ENCONTRADO", str(exc), {"pedido": pedido.para_dict()}
        ) from exc
    corpo = {"pedido": pedido.para_dict(), "quantidade": len(itens),
             "certificados": [i.para_dict() for i in itens]}  # fmt: skip
    for item in corpo["certificados"]:
        _assinar_item(item, publicador, cfg.link_validade_seg)
    log.info(
        json.dumps(
            {
                "evento": "link_portal",
                "request_id": request_id_de(request),
                "chave": chave.prefixo,
                "ip": auth.ip_de(request),
                "pedido": pedido.para_dict(),
                "certificados": [
                    {"chave": i["chave"], "situacao": i["situacao"]} for i in corpo["certificados"]
                ],
                "duracao_ms": round((time.monotonic() - inicio) * 1000),
            },
            ensure_ascii=False,
        )
    )
    return _ok(request, corpo)


# ---------------------------------------------------------------- auxiliares
def _pedido_verificacao(req: VerificacaoIn) -> PedidoVerificacao:
    try:
        return PedidoVerificacao.criar(req.administradora, req.cpf_cnpj)
    except PedidoInvalido as exc:
        raise ErroApi(400, "PEDIDO_INVALIDO", str(exc)) from exc


def _pedido_emissao(req: PedidoIn) -> PedidoPortal:
    try:
        return PedidoPortal.criar(
            req.administradora, req.cpf_cnpj, req.vigencia, req.fatura, req.certificado
        )
    except PedidoInvalido as exc:
        raise ErroApi(400, "PEDIDO_INVALIDO", str(exc)) from exc


def _capturar_banco(acao):
    """Banco fora do ar vira 503 com codigo proprio, nunca 500 (ADR-09)."""
    from certgen.adapters.firebird.conexao import ErroConexao

    try:
        return acao()
    except (ErroConexao, ErroRepositorio) as exc:
        log.error(json.dumps({"evento": "banco_indisponivel", "tipo": type(exc).__name__}))
        raise ErroApi(
            503, "BANCO_INDISPONIVEL", "banco de dados indisponivel; tente mais tarde"
        ) from exc


def _assinar_item(item: dict, publicador: PublicadorArquivos, validade: int) -> None:
    """ADR-09 — troca o link permanente do item por um assinado; falha vira `falha`."""
    permanente = item.get("link")
    if not permanente:
        item["link_expira_em"] = None
        return
    try:
        item["link"] = publicador.link_temporario(permanente, validade)
        item["link_expira_em"] = (datetime.now(UTC) + timedelta(seconds=validade)).replace(
            microsecond=0
        ).isoformat()
    except ErroPublicacao as exc:
        item.update(link=None, link_expira_em=None, situacao="falha",
                    motivo=f"[ErroPublicacao] {exc}")  # fmt: skip


def _registrar_log(
    request: Request, chave: ChaveApi, pedido: PedidoPortal, itens, inicio: float, http: int
) -> None:
    """RNF-13 — sem chave de autenticacao e sem nome do segurado."""
    log.info(
        json.dumps(
            {
                "evento": "emissao_portal",
                "request_id": request_id_de(request),
                "chave": chave.prefixo,
                "ip": auth.ip_de(request),
                "pedido": pedido.para_dict(),
                "http": http,
                "certificados": [
                    {"chave": i.chave.para_dict(), "situacao": i.situacao, "motivo": i.motivo}
                    for i in itens
                ],
                "duracao_ms": round((time.monotonic() - inicio) * 1000),
            },
            ensure_ascii=False,
        )
    )


# --------------------------------------------------------------- instalacao
def instalar_portal(aplicacao: FastAPI) -> None:
    """Acrescenta as rotas /v1 e o envelope de erro a uma aplicacao FastAPI, ANTES de ela
    subir (os tratadores entram na pilha na primeira requisicao). Usado pela app propria
    (`certgen api`) e pela tela (`certgen servidor`, combinado.py). O X-Request-Id vai
    em toda resposta montada por `_ok`/`resposta_erro`."""
    if getattr(aplicacao.state, "portal_incluido", False):
        return
    aplicacao.include_router(router)
    aplicacao.add_exception_handler(ErroApi, _tratar_erro_api)
    aplicacao.add_exception_handler(StarletteHTTPException, _tratar_http)
    aplicacao.add_exception_handler(RequestValidationError, _tratar_validacao)
    aplicacao.add_exception_handler(Exception, _tratar_inesperado)
    aplicacao.state.portal_incluido = True


app = FastAPI(
    title="API de Certificados FedCorp (portal)",
    version=__version__,
    description=(
        "UC-12 — emite, publica no S3 e devolve link assinado + JSON. "
        "UC-13 — verifica se o CPF/CNPJ e segurado da administradora e devolve as 3 "
        "vigencias mais recentes (fatura, certificado, produto) para alimentar a emissao. "
        "ADR-09 — link assinado sob demanda, administradoras da chave. "
        "Autenticacao por X-API-Key; erros no envelope {codigo, mensagem, request_id, detalhes}."
    ),
    docs_url="/v1/docs",
    openapi_url="/v1/openapi.json",
    redoc_url=None,
)
instalar_portal(app)
