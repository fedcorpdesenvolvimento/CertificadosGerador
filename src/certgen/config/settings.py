"""Configuracao por variaveis de ambiente (.env).

Modelo copiado de U:\\--2021\\04-EnvioPorto\\config.py (03/09/2026), que por sua
vez segue o FedHub-Backend:

- credenciais moram no .env, carregado com python-dotenv por caminho ABSOLUTO
  (raiz do projeto), para funcionar de qualquer diretorio de trabalho;
- as variaveis do Firebird usam os MESMOS nomes do FedHub (FB_HOST, FB_PORT,
  FB_DATABASE, FB_USER, FB_PASSWORD, FB_CHARSET, FB_POOL_SIZE), para que o
  mesmo .env sirva nos dois projetos e na migracao futura;
- variavel obrigatoria ausente derruba com mensagem clara; credencial nunca
  tem default (RNF-06).

Diferenca em relacao ao EnvioPorto: la a leitura acontece na importacao do
modulo; aqui e sob demanda (`Config.do_ambiente()`), porque o dominio e os
testes unitarios rodam sem banco (ADR-01).

ADR-01 — CERTGEN_REPOSITORIO escolhe o adaptador (firebird | api).
RN-22  — CERTGEN_APOLICES_MASSA substitui o literal da linha 711 do .pas.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

RAIZ_PROJETO = Path(__file__).resolve().parents[3]
ARQUIVO_ENV = RAIZ_PROJETO / ".env"


class ConfiguracaoAusente(RuntimeError):
    """Variavel obrigatoria nao definida no .env nem no ambiente."""


def carregar_dotenv(caminho: Path | None = None, sobrescrever: bool = False) -> bool:
    """Carrega o .env (padrao: raiz do projeto). O ambiente real tem precedencia.

    Retorna True se algum arquivo foi lido.
    """
    return load_dotenv(dotenv_path=caminho or ARQUIVO_ENV, encoding="utf-8", override=sobrescrever)


def env_obrigatoria(nome: str) -> str:
    """Le uma env obrigatoria; falha com mensagem clara se ausente (padrao FedHub)."""
    valor = os.getenv(nome)
    if not valor:
        raise ConfiguracaoAusente(
            f"Variavel obrigatoria ausente no .env: {nome}. "
            f"Copie o .env.example para .env e preencha (pasta {RAIZ_PROJETO})."
        )
    return valor


@dataclass(frozen=True)
class ConfigFirebird:
    host: str
    port: int
    database: str
    user: str
    password: str
    charset: str = "WIN1252"
    pool_size: int = 5

    @classmethod
    def do_ambiente(cls) -> ConfigFirebird:
        """Mesmos nomes e mesma politica do DB_CONFIG do EnvioPorto."""
        return cls(
            host=env_obrigatoria("FB_HOST"),
            port=int(os.getenv("FB_PORT", "3050")),
            database=env_obrigatoria("FB_DATABASE"),
            user=env_obrigatoria("FB_USER"),
            password=env_obrigatoria("FB_PASSWORD"),
            # O legado deste projeto grava acentos; WIN1252 e o charset dos
            # modulos Porto no EnvioPorto. (La o padrao e ASCII por heranca do Vida.)
            charset=os.getenv("FB_CHARSET", "WIN1252") or "WIN1252",
            pool_size=int(os.getenv("FB_POOL_SIZE", "5")),
        )

    @property
    def dsn(self) -> str:
        return f"{self.host}/{self.port}:{self.database}"

    def __repr__(self) -> str:  # nunca vazar a senha em log
        return (
            f"ConfigFirebird(host={self.host!r}, port={self.port}, database={self.database!r}, "
            f"user={self.user!r}, password='***', charset={self.charset!r}, "
            f"pool_size={self.pool_size})"
        )


@dataclass(frozen=True)
class Config:
    repositorio: str
    firebird: ConfigFirebird | None
    api_base_url: str
    api_token: str
    pasta_saida: Path
    apolices_massa: tuple[str, ...] = field(default_factory=tuple)
    susep_corretora: str = "00000202049583"  # RN-25 — fixo nesta fase

    @classmethod
    def do_ambiente(cls) -> Config:
        carregar_dotenv()
        repositorio = os.getenv("CERTGEN_REPOSITORIO", "firebird").strip().lower()
        apolices = tuple(
            a.strip() for a in os.getenv("CERTGEN_APOLICES_MASSA", "").split(",") if a.strip()
        )
        return cls(
            repositorio=repositorio,
            # so exige as FB_* quando o adaptador escolhido e o Firebird
            firebird=ConfigFirebird.do_ambiente() if repositorio == "firebird" else None,
            api_base_url=os.getenv("CERTGEN_API_BASE_URL", ""),
            api_token=os.getenv("CERTGEN_API_TOKEN", ""),
            pasta_saida=Path(os.getenv("CERTGEN_PASTA_SAIDA", "saida")),
            apolices_massa=apolices,
            susep_corretora=os.getenv("CERTGEN_SUSEP_CORRETORA", "00000202049583").strip(),
        )
