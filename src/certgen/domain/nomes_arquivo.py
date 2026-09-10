"""RN-11 / RN-12 / RN-13 / RN-17b / RN-19 — nomes de arquivo e pastas.

RN-11:  um unico padrao de 6 campos para os dois fluxos, SEMPRE com produto
        resolvido (DEF-09):
        {portal}_{cpf_cnpj}_{produto}_{apolice}_{certificado_sanitizado}_{fatura}.{pdf|json}
RN-17b: sanitizacao do certificado; alem da lista do legado, rejeita : * ? " < >
        e caracteres de controle.
RN-12:  nome do consolidado com carimbo YYYYMMDD-HHMMSS.
RN-13:  nunca sobrescrever silenciosamente: sufixo " (n)".
RN-19:  competencia MMYYYY com zero a esquerda, calculada com o mes e o ano
        como numeros (DEF-16: data ausente e erro, nao 121899).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

# Linhas 998-1002 do .pas
_SANITIZE = str.maketrans({"/": "-", "\\": "-", "|": "-", ".": "", " ": ""})
_PROIBIDOS = set(':*?"<>')
_PRODUTO = re.compile(r"^\d{4}$")
_DIGITOS = re.compile(r"^\d+$")


class NomeArquivoInvalido(ValueError):
    """Algum campo do nome nao atende RN-11 / RN-17b."""


def sanitizar_certificado(certificado: str) -> str:
    """RN-17b.

    >>> sanitizar_certificado('CF1DI/AP.602')
    'CF1DI-AP602'
    >>> sanitizar_certificado('3082/01/AP 1302')
    '3082-01-AP1302'
    """
    if certificado is None or not certificado.strip():
        raise NomeArquivoInvalido("certificado vazio")
    invalidos = sorted({c for c in certificado if c in _PROIBIDOS or ord(c) < 32})
    if invalidos:
        raise NomeArquivoInvalido(
            f"certificado {certificado!r} contem caracteres proibidos: {invalidos}"
        )
    resultado = certificado.translate(_SANITIZE)
    if not resultado:
        raise NomeArquivoInvalido(f"certificado {certificado!r} ficou vazio apos sanitizar")
    return resultado


def nome_base_certificado(
    portal: int | None,
    cpf_cnpj: str,
    produto: str,
    apolice: str,
    certificado: str,
    fatura: int,
) -> str:
    """RN-11 — nome sem extensao. Valida cada campo; falha alto (ADR-04)."""
    if portal is None:
        portal = 0  # coalesce(codigo_pedido_port, 0) — 7.2
    if not isinstance(portal, int) or isinstance(portal, bool) or portal < 0:
        raise NomeArquivoInvalido(f"portal deve ser inteiro >= 0: {portal!r}")
    if not cpf_cnpj or not _DIGITOS.match(cpf_cnpj):
        raise NomeArquivoInvalido(f"cpf_cnpj deve conter apenas digitos: {cpf_cnpj!r}")
    if not produto or not _PRODUTO.match(produto):
        # DEF-09 fotografado: '0_05554363733__15008_381066.pdf'. Passa a falhar explicitamente.
        raise NomeArquivoInvalido(
            f"produto deve ter 4 digitos, recebido {produto!r} (RN-11 / RN-03.3 / DEF-09)"
        )
    if not apolice or not _DIGITOS.match(str(apolice)):
        raise NomeArquivoInvalido(f"apolice invalida: {apolice!r}")
    if not isinstance(fatura, int) or isinstance(fatura, bool):
        raise NomeArquivoInvalido(f"fatura deve ser inteiro (RD 4.2): {fatura!r}")
    cert = sanitizar_certificado(certificado)
    return f"{portal}_{cpf_cnpj}_{produto}_{apolice}_{cert}_{fatura}"


def nome_arquivo_certificado(
    portal: int | None,
    cpf_cnpj: str,
    produto: str,
    apolice: str,
    certificado: str,
    fatura: int,
    extensao: str = "pdf",
) -> str:
    """RN-11 — `{base}.pdf` ou `{base}.json`."""
    base = nome_base_certificado(portal, cpf_cnpj, produto, apolice, certificado, fatura)
    return f"{base}.{extensao.lstrip('.')}"


def nome_consolidado(
    apolice: str, seq: int, fatura: int, instante: datetime, extensao: str = "pdf"
) -> str:
    """RN-12 — certificados_{apolice}_{seq}_{fatura}_{YYYYMMDD-HHMMSS}.{ext}"""
    carimbo = instante.strftime("%Y%m%d-%H%M%S")
    return f"certificados_{apolice}_{seq}_{fatura}_{carimbo}.{extensao.lstrip('.')}"


def competencia(data: date | None) -> str:
    """RN-19 — MMYYYY. julho/2026 -> '072026'. Data ausente e erro (DEF-16)."""
    if data is None:
        raise NomeArquivoInvalido("competencia exige data; DateEdit vazio produzia 121899 (DEF-16)")
    return f"{data.month:02d}{data.year}"


def pasta_lote(raiz: Path, administradora: str, data_competencia: date) -> Path:
    """RN-19 — {raiz}/{administradora}/{competencia}"""
    return raiz / administradora / competencia(data_competencia)


def caminho_publicacao(
    administradora: str, produto: str, data_competencia: date | None, fatura: int, nome_pdf: str
) -> str:
    """RN-29 — chave do objeto no bucket: {administradora}/{produto}/{competencia}/{fatura}/{pdf}.

    E o `pstfin` do legado (8.1) com produto (RN-03) e competencia (RN-19) corrigidos.
    Sempre com '/', independente do sistema de arquivos.
    """
    if not administradora or not produto or not nome_pdf:
        raise NomeArquivoInvalido("caminho de publicacao exige administradora, produto e nome")
    return f"{administradora}/{produto}/{competencia(data_competencia)}/{fatura}/{nome_pdf}"


def resolver_colisao(
    caminho: Path, existe: Callable[[Path], bool] = Path.exists
) -> tuple[Path, bool]:
    """RN-13 — se `caminho` existe, devolve `nome (n).ext` com o menor n >= 1 livre.

    Retorna (caminho_final, houve_colisao). `existe` e injetavel para teste.
    """
    if not existe(caminho):
        return caminho, False
    n = 1
    while True:
        candidato = caminho.with_name(f"{caminho.stem} ({n}){caminho.suffix}")
        if not existe(candidato):
            return candidato, True
        n += 1
