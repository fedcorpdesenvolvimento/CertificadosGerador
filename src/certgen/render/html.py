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

# Logotipo da seguradora por cod_seguradora. So a Bradesco aparece no PDF de referencia.
# Outras seguradoras: caixa vazia ate o negocio fornecer a imagem (GAP-20).
LOGOS_SEGURADORA: dict[str, str] = {
    "0000000104": "logo_bradesco",
}


@dataclass(frozen=True)
class DadosRender:
    """O que o template precisa alem do Certificado."""

    data_emissao: date  # RN-21
    exibe_premio: bool  # RF-10


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
    ctx: ContextoTemplate = cert.contexto_template(exibe_premio=dados.exibe_premio)
    imagens = imagens_base64()
    logo_seg = LOGOS_SEGURADORA.get(cert.contrato.cod_seguradora or "")
    por_codigo = {c.codigo: c for c in cert.coberturas}
    return ambiente().get_template("certificado.html.j2").render(
        cert=cert,
        ctx=ctx,
        cob=por_codigo,
        data_emissao=dados.data_emissao,
        imagens=imagens,
        logo_seguradora=imagens.get(logo_seg) if logo_seg else None,
        css=(PASTA_TEMPLATES / "certificado.css").read_text(encoding="utf-8"),
        titulo_produto=TITULO_PRODUTO,
        estipulante=ESTIPULANTE,
        central_atendimento=CENTRAL_ATENDIMENTO,
        central_fedcorp=CENTRAL_FEDCORP,
        email_sac=EMAIL_SAC,
        link_condicoes=LINK_CONDICOES,
    )
