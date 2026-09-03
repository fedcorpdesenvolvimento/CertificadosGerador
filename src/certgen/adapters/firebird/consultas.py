"""RD-17 / RN-06 / RN-07 — carga de `queries.sql` e composicao de filtros.

Os blocos sao delimitados por `-- name: <nome>`. Filtros opcionais entram no
marcador /*FILTROS*/ como predicados `AND ...` com bind `?`; os valores vao
em lista, na mesma ordem. Nunca se concatena valor em SQL.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

_ARQUIVO = Path(__file__).with_name("queries.sql")
_MARCADOR = "/*FILTROS*/"
_CABECALHO = re.compile(r"^--\s*name:\s*(\w+)\s*$", re.MULTILINE)


class ConsultaDesconhecida(KeyError):
    pass


@lru_cache(maxsize=1)
def _blocos(caminho: Path = _ARQUIVO) -> dict[str, str]:
    texto = caminho.read_text(encoding="utf-8")
    partes = _CABECALHO.split(texto)
    # partes = [preambulo, nome1, corpo1, nome2, corpo2, ...]
    blocos: dict[str, str] = {}
    for nome, corpo in zip(partes[1::2], partes[2::2], strict=True):
        linhas = [ln for ln in corpo.strip().splitlines() if not ln.lstrip().startswith("--")]
        blocos[nome] = "\n".join(linhas).strip()
    return blocos


def consulta(nome: str) -> str:
    try:
        return _blocos()[nome]
    except KeyError:
        raise ConsultaDesconhecida(f"bloco '-- name: {nome}' nao existe em queries.sql") from None


def nomes() -> tuple[str, ...]:
    return tuple(_blocos())


@dataclass
class Filtros:
    """RN-07 — lista de predicados e parametros, montada condicionalmente."""

    predicados: list[str] = field(default_factory=list)
    parametros: list[object] = field(default_factory=list)

    def igual(self, coluna: str, valor: object) -> Filtros:
        """Adiciona `coluna = ?` se valor nao for None."""
        if valor is not None:
            self.predicados.append(f"{coluna} = ?")
            self.parametros.append(valor)
        return self

    def em(self, coluna: str, valores: list[object] | tuple[object, ...] | None) -> Filtros:
        """Adiciona `coluna IN (?, ?, ...)` se houver valores."""
        if valores:
            marcadores = ", ".join("?" for _ in valores)
            self.predicados.append(f"{coluna} IN ({marcadores})")
            self.parametros.extend(valores)
        return self

    def aplicar(self, sql: str) -> tuple[str, list[object]]:
        if _MARCADOR not in sql:
            if self.predicados:
                raise ValueError("consulta sem marcador /*FILTROS*/ nao aceita filtros")
            return sql, list(self.parametros)
        trecho = "".join(f"  AND {p}\n" for p in self.predicados)
        return sql.replace(_MARCADOR, trecho.rstrip("\n")), list(self.parametros)


def montar(nome: str, filtros: Filtros | None = None) -> tuple[str, list[object]]:
    """Devolve (sql, parametros) prontos para `cursor.execute`."""
    return (filtros or Filtros()).aplicar(consulta(nome))
