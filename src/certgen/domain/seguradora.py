"""RN-28 — Seguradora emissora e o logotipo que ela imprime (GAP-20).

O mapa `cod_seguradora -> (nome, logo)` e DADO em config/seguradoras.toml, como o
mapa de produtos (RN-03.2). Codigo desconhecido resolve para None: a caixa sai
vazia e o certificado recebe o aviso LOGO_SEGURADORA_AUSENTE (RD-23).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

_ARQUIVO_PADRAO = Path(__file__).resolve().parents[1] / "config" / "seguradoras.toml"


class CatalogoSeguradorasInvalido(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Seguradora:
    codigo: str
    nome: str
    logo: str  # nome do arquivo em render/templates/img/seguradoras/
    motivo: str | None = None


class CatalogoSeguradoras:
    def __init__(self, seguradoras: list[Seguradora]) -> None:
        self._por_codigo: dict[str, Seguradora] = {}
        for s in seguradoras:
            if not s.codigo or not s.nome or not s.logo:
                raise CatalogoSeguradorasInvalido(f"entrada incompleta: {s}")
            if s.codigo in self._por_codigo:
                raise CatalogoSeguradorasInvalido(f"codigo duplicado: {s.codigo}")
            self._por_codigo[s.codigo] = s

    @classmethod
    def carregar(cls, caminho: Path | None = None) -> CatalogoSeguradoras:
        with (caminho or _ARQUIVO_PADRAO).open("rb") as fh:
            dados = tomllib.load(fh)
        return cls(
            [
                Seguradora(
                    codigo=str(s["codigo"]),
                    nome=str(s["nome"]),
                    logo=str(s["logo"]),
                    motivo=s.get("motivo"),
                )
                for s in dados.get("seguradora", [])
            ]
        )

    def resolver(self, cod_seguradora: str | None) -> Seguradora | None:
        if not cod_seguradora:
            return None
        return self._por_codigo.get(str(cod_seguradora).strip())

    @property
    def todas(self) -> tuple[Seguradora, ...]:
        return tuple(self._por_codigo.values())
