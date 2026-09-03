"""RD-12 — Documento do segurado (CPF/CNPJ).

`tipo` deriva do comprimento apos remover nao-digitos: 11 -> CPF, 14 -> CNPJ,
outro -> INDEFINIDO com aviso. Necessario porque o legado grava o campo
com e sem mascara (DEF-08). Mascaras de saida conforme RN-14.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from certgen.domain.avisos import Aviso, CodigoAviso

_NAO_DIGITO = re.compile(r"\D+")


class TipoDocumento(StrEnum):
    CPF = "CPF"
    CNPJ = "CNPJ"
    INDEFINIDO = "INDEFINIDO"


def somente_digitos(texto: str | None) -> str:
    return _NAO_DIGITO.sub("", texto or "")


def formatar_cpf(digitos: str) -> str:
    """RN-14: 000.000.000-00"""
    d = digitos
    return f"{d[0:3]}.{d[3:6]}.{d[6:9]}-{d[9:11]}"


def formatar_cnpj(digitos: str) -> str:
    """RN-14: 00.000.000/0000-00"""
    d = digitos
    return f"{d[0:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:14]}"


@dataclass(frozen=True, slots=True)
class Documento:
    tipo: TipoDocumento
    numero: str  # apenas digitos, como vai no nome do arquivo (RN-11)
    formatado: str  # como vai no PDF (RN-14)
    original: str  # valor bruto do banco, preservado para auditoria (RD-13)

    @classmethod
    def de(cls, texto: str | None) -> Documento:
        digitos = somente_digitos(texto)
        if len(digitos) == 11:
            return cls(TipoDocumento.CPF, digitos, formatar_cpf(digitos), texto or "")
        if len(digitos) == 14:
            return cls(TipoDocumento.CNPJ, digitos, formatar_cnpj(digitos), texto or "")
        return cls(TipoDocumento.INDEFINIDO, digitos, digitos, texto or "")

    @property
    def indefinido(self) -> bool:
        return self.tipo is TipoDocumento.INDEFINIDO

    def avisos(self) -> list[Aviso]:
        if self.indefinido:
            return [
                Aviso(
                    CodigoAviso.DOCUMENTO_INDEFINIDO,
                    f"cpf_cnpj {self.original!r} tem {len(self.numero)} digitos; esperado 11 ou 14",
                )
            ]
        return []

    def para_dict(self) -> dict[str, str]:
        return {"tipo": str(self.tipo), "numero": self.numero, "formatado": self.formatado}
