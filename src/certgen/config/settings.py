"""Leitura das variaveis de ambiente descritas em .env.example.

RNF-06 — credenciais so entram por ambiente, nunca pelo codigo.
ADR-01 — CERTGEN_REPOSITORIO escolhe o adaptador (firebird | api).
RN-22  — CERTGEN_APOLICES_MASSA substitui o literal da linha 711 do .pas.

Sem dependencia de python-dotenv: um .env na raiz do projeto (ou no
diretorio atual) e lido por um parser minimo, e o ambiente real do
processo sempre tem precedencia.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_RAIZ_PROJETO = Path(__file__).resolve().parents[3]


def carregar_dotenv(caminho: Path | None = None) -> dict[str, str]:
    """Le um arquivo .env simples (CHAVE=valor, # comentario) sem sobrescrever
    variaveis ja presentes no ambiente. Retorna o que foi aplicado."""
    candidatos = [caminho] if caminho else [Path.cwd() / ".env", _RAIZ_PROJETO / ".env"]
    aplicadas: dict[str, str] = {}
    for arq in candidatos:
        if arq is None or not arq.is_file():
            continue
        for linha in arq.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            chave, _, valor = linha.partition("=")
            chave, valor = chave.strip(), valor.strip().strip('"').strip("'")
            if chave and chave not in os.environ:
                os.environ[chave] = valor
                aplicadas[chave] = valor
        break
    return aplicadas


@dataclass(frozen=True)
class ConfigFirebird:
    host: str
    port: int
    database: str
    user: str
    password: str
    charset: str = "WIN1252"

    @property
    def dsn(self) -> str:
        return f"{self.host}/{self.port}:{self.database}"

    def completa(self) -> bool:
        return all([self.host, self.database, self.user, self.password])


@dataclass(frozen=True)
class Config:
    repositorio: str
    firebird: ConfigFirebird
    api_base_url: str
    api_token: str
    pasta_saida: Path
    apolices_massa: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def do_ambiente(cls) -> Config:
        carregar_dotenv()
        env = os.environ.get
        apolices = tuple(
            a.strip() for a in env("CERTGEN_APOLICES_MASSA", "").split(",") if a.strip()
        )
        return cls(
            repositorio=env("CERTGEN_REPOSITORIO", "firebird").strip().lower(),
            firebird=ConfigFirebird(
                host=env("FIREBIRD_HOST", "localhost"),
                port=int(env("FIREBIRD_PORT", "3050") or 3050),
                database=env("FIREBIRD_DATABASE", ""),
                user=env("FIREBIRD_USER", ""),
                password=env("FIREBIRD_PASSWORD", ""),
                charset=env("FIREBIRD_CHARSET", "WIN1252") or "WIN1252",
            ),
            api_base_url=env("CERTGEN_API_BASE_URL", ""),
            api_token=env("CERTGEN_API_TOKEN", ""),
            pasta_saida=Path(env("CERTGEN_PASTA_SAIDA", "saida")),
            apolices_massa=apolices,
        )
