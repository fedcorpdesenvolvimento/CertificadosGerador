"""RD-23 — Avisos de emissao.

Toda anomalia que NAO impede a emissao vai para `_meta.avisos` com codigo
estavel (ADR-04). O vocabulario minimo e o da tabela em 9.2 da especificacao.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CodigoAviso(StrEnum):
    ABREV_ADM_AUSENTE = "ABREV_ADM_AUSENTE"  # RN-20 — COD_0800 incompleto
    FINAL_VIG_AUSENTE = "FINAL_VIG_AUSENTE"  # DEF-06 — final_vig nula ou zero-Delphi
    COB_INCENDIO_DIVERGENTE = "COB_INCENDIO_DIVERGENTE"  # RN-02 — soma != banco
    DOCUMENTO_INDEFINIDO = "DOCUMENTO_INDEFINIDO"  # RD-12 — nem 11 nem 14 digitos
    PORTAL_AUSENTE = "PORTAL_AUSENTE"  # GAP-11 — codigo_pedido_port nulo
    PRODUTO_POR_EXCECAO = "PRODUTO_POR_EXCECAO"  # RN-03.1 — regra por administradora


@dataclass(frozen=True, slots=True)
class Aviso:
    """Um aviso registrado durante a montagem de um certificado."""

    codigo: CodigoAviso
    detalhe: str = ""

    def para_dict(self) -> dict[str, str]:
        return {"codigo": str(self.codigo), "detalhe": self.detalhe}

    def __str__(self) -> str:
        return f"{self.codigo}: {self.detalhe}" if self.detalhe else str(self.codigo)
