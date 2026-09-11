"""Fase 8 — APIs para o portal (secao 11.1: RF-18, RF-19, RF-20, RN-30, RNF-10b, RNF-13).

Dois endpoints autenticados pela mesma chave (decisao de 11/09/2026):
  POST /v1/certificados/emitir   — UC-12: emite, publica no S3, devolve link + JSON (RD-29)
  POST /v1/segurados/verificar   — UC-13: {"existe": bool}; login do segurado no portal

Aplicacao FastAPI SEPARADA da tela (`certgen web`): sem paginas, sem cascata,
sem Sair/Procurar. Sobe por `certgen api` (RF-19).

RN-30: chave unica em CERTGEN_API_KEY, header X-API-Key, comparacao em tempo
constante; a chave nunca aparece em log nem em resposta.
RNF-13: um registro de log JSON por chamada, sem chave e sem nome do segurado.
Endpoints sincronos (`def`): rodam no threadpool do Starlette, como na tela.
"""

from __future__ import annotations

import hmac
import json
import logging
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import date
from functools import lru_cache

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from certgen import __version__
from certgen.application.emitir_certificados import OpcoesEmissao, RenderizadorPdf
from certgen.application.emitir_portal import (
    NenhumCertificado,
    PedidoInvalido,
    PedidoPortal,
    PedidoVerificacao,
    emitir_para_portal,
    verificar_segurado,
)
from certgen.application.ports import PublicadorArquivos, RegistroLinks, RepositorioCertificados
from certgen.config.settings import Config

log = logging.getLogger("certgen.api")

app = FastAPI(
    title="APIs do gerador de certificados para o portal",
    version=__version__,
    description=(
        "UC-12 — emite, publica no S3 e devolve link + JSON. "
        "UC-13 — verifica se o CPF/CNPJ e segurado ativo da administradora. "
        "Autenticacao por X-API-Key."
    ),
)


# --------------------------------------------------------------- dependencias
@lru_cache(maxsize=1)
def _config() -> Config:
    return Config.do_ambiente()


def get_config() -> Config:
    return _config()


def get_api_key() -> str:
    """RN-30 — sem chave configurada o processo nao serve nada."""
    return _config().exigir_api_key()


def autenticar(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    esperada: str = Depends(get_api_key),
) -> None:
    """RN-30 — comparacao em tempo constante; mensagem nao revela nada."""
    if not x_api_key or not hmac.compare_digest(x_api_key.encode(), esperada.encode()):
        raise HTTPException(401, "chave de autenticacao ausente ou invalida")


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
        ..., examples=["2026-07-01"], description="= inicio_vig (RN-31), ISO 8601"
    )


class VerificacaoIn(BaseModel):
    """RF-20 — sem vigencia: a pergunta e 'e segurado ativo HOJE?' (RN-35)."""

    administradora: str = Field(..., examples=["0000001192"], description="pessoas.pessoa")
    cpf_cnpj: str = Field(
        ..., examples=["330.163.307-25"], description="CPF ou CNPJ; pontuacao aceita"
    )


class VerificacaoOut(BaseModel):
    existe: bool


# ------------------------------------------------------------------ endpoints
@app.get("/v1/saude", dependencies=[Depends(autenticar)])
def saude() -> dict:
    """RF-18 — o portal testa a chave aqui."""
    return {"ok": True, "versao": __version__}


@app.post(
    "/v1/segurados/verificar",
    dependencies=[Depends(autenticar)],
    response_model=VerificacaoOut,
    responses={400: {"description": "administradora vazia ou documento sem 11/14 digitos"}},
)
def verificar(
    req: VerificacaoIn,
    repo: RepositorioCertificados = Depends(get_repositorio),
):
    """UC-13 / RF-20 — {"existe": true|false}. Nenhum dado do segurado sai (RN-35)."""
    inicio = time.monotonic()
    try:
        pedido = PedidoVerificacao.criar(req.administradora, req.cpf_cnpj)
    except PedidoInvalido as exc:
        return JSONResponse({"erro": str(exc)}, status_code=400)
    existe = verificar_segurado(repo, pedido, date.today())
    log.info(  # RNF-13: sem chave, sem nome
        json.dumps(
            {
                "evento": "verificacao_portal",
                "pedido": pedido.para_dict(),
                "existe": existe,
                "http": 200,
                "duracao_ms": round((time.monotonic() - inicio) * 1000),
            },
            ensure_ascii=False,
        )
    )
    return VerificacaoOut(existe=existe)


@app.post("/v1/certificados/emitir", dependencies=[Depends(autenticar)])
def emitir(
    req: PedidoIn,
    repo: RepositorioCertificados = Depends(get_repositorio),
    publicador: PublicadorArquivos = Depends(get_publicador),
    registro: RegistroLinks = Depends(get_registro),
    cfg: Config = Depends(get_config),
    fabrica_render: FabricaRender = Depends(get_fabrica_render),
):
    """UC-12 / RF-18. 200 com ao menos um link; 404 sem certificado; 502 todos falharam."""
    inicio = time.monotonic()
    try:
        pedido = PedidoPortal.criar(req.administradora, req.cpf_cnpj, req.vigencia)
    except PedidoInvalido as exc:
        return JSONResponse({"erro": str(exc)}, status_code=400)

    opcoes = OpcoesEmissao(pasta_saida=cfg.pasta_saida, modo_conexao="firebird-local")  # RN-34
    from certgen.render.pdf import ErroRenderizacao

    try:
        with fabrica_render() as renderizar:
            resposta = emitir_para_portal(repo, publicador, registro, pedido, opcoes, renderizar)
    except NenhumCertificado as exc:
        _registrar_log(pedido, [], inicio, http=404)
        return JSONResponse({"erro": str(exc), "pedido": pedido.para_dict()}, status_code=404)
    except ErroRenderizacao as exc:
        _registrar_log(pedido, [], inicio, http=503)
        return JSONResponse({"erro": str(exc), "pedido": pedido.para_dict()}, status_code=503)

    status = 200 if resposta.algum_link else 502
    _registrar_log(pedido, resposta.certificados, inicio, http=status)
    return JSONResponse(resposta.para_dict(), status_code=status)


def _registrar_log(pedido: PedidoPortal, itens, inicio: float, http: int) -> None:
    """RNF-13 — sem chave de autenticacao e sem nome do segurado."""
    log.info(
        json.dumps(
            {
                "evento": "emissao_portal",
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
