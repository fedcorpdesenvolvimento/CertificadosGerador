"""Certificado -> HTML via Jinja2 (ADR-02, ADR-05, ADR-06).

Um unico template, `certificado.html.j2`, governado por `ContextoTemplate`.
Imagens entram como data URI para o HTML ser autocontido (abre no navegador,
vai para o Chromium sem servidor de arquivos).
"""

from __future__ import annotations

import base64
import mimetypes
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from certgen.domain.certificado import ESTIPULANTE, Certificado, ContextoTemplate
from certgen.render.filtros import FILTROS

PASTA_TEMPLATES = Path(__file__).with_name("templates")
PASTA_IMAGENS = PASTA_TEMPLATES / "img"
TITULO_PRODUTO = "Total Conteúdo"  # constante do PDF de referencia (ADR-06)
CENTRAL_ATENDIMENTO = "0800 770 4362"
CENTRAL_FEDCORP = "0800 251 6001"
EMAIL_SAC = "sac@grupofedcorp.com.br"
LINK_CONDICOES = "http://fedcorp.com.br/suporte/condicao-doc/condicao_geral_fedcorp.pdf"

PASTA_LOGOS_SEGURADORAS = PASTA_IMAGENS / "seguradoras"  # RN-28 — arquivos de seguradoras.toml


@dataclass(frozen=True)
class DadosRender:
    """O que o template precisa alem do Certificado."""

    data_emissao: date  # RN-21
    exibe_premio: bool  # RF-10
    faz_tudo_lar: bool | None = None  # ADR-06 — escolha do operador; None = derivacao RN-18


@lru_cache(maxsize=1)
def imagens_base64() -> dict[str, str]:
    """{nome_sem_extensao: data URI} para todos os arquivos de templates/img."""
    saida: dict[str, str] = {}
    for arq in sorted(PASTA_IMAGENS.iterdir()):
        if arq.suffix.lower() not in {".png", ".jpg", ".jpeg", ".svg"}:
            continue
        mime = mimetypes.guess_type(arq.name)[0] or "application/octet-stream"
        dados = base64.b64encode(arq.read_bytes()).decode("ascii")
        saida[arq.stem] = f"data:{mime};base64,{dados}"
    return saida


def _data_uri(arq: Path) -> str:
    mime = mimetypes.guess_type(arq.name)[0] or "application/octet-stream"
    return f"data:{mime};base64,{base64.b64encode(arq.read_bytes()).decode('ascii')}"


@lru_cache(maxsize=32)
def logo_seguradora_base64(arquivo: str | None) -> str | None:
    """RN-28 — data URI do logotipo, ou None se a seguradora nao tem entrada ou o
    arquivo ainda nao foi colocado em img/seguradoras/ (a caixa sai vazia)."""
    if not arquivo:
        return None
    caminho = PASTA_LOGOS_SEGURADORAS / Path(arquivo).name
    return _data_uri(caminho) if caminho.is_file() else None


@lru_cache(maxsize=1)
def ambiente() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(PASTA_TEMPLATES)),
        autoescape=select_autoescape(["html", "j2"]),
        undefined=StrictUndefined,  # variavel esquecida e erro, nao texto vazio (ADR-04)
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters.update(FILTROS)
    return env


def renderizar_html(cert: Certificado, dados: DadosRender) -> str:
    ctx: ContextoTemplate = cert.contexto_template(
        exibe_premio=dados.exibe_premio, faz_tudo_lar=dados.faz_tudo_lar
    )
    imagens = imagens_base64()
    seg = cert.contrato.seguradora
    logo_seg = logo_seguradora_base64(seg.logo if seg else None)
    por_codigo = {c.codigo: c for c in cert.coberturas}
    return ambiente().get_template("certificado.html.j2").render(
        cert=cert,
        ctx=ctx,
        cob=por_codigo,
        data_emissao=dados.data_emissao,
        imagens=imagens,
        logo_seguradora=logo_seg,
        nome_seguradora=seg.nome if seg else "",
        css=(PASTA_TEMPLATES / "certificado.css").read_text(encoding="utf-8"),
        titulo_produto=TITULO_PRODUTO,
        estipulante=ESTIPULANTE,
        central_atendimento=CENTRAL_ATENDIMENTO,
        central_fedcorp=CENTRAL_FEDCORP,
        email_sac=EMAIL_SAC,
        link_condicoes=LINK_CONDICOES,
    )
