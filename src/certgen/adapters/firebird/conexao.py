"""Conexao ao Firebird (Fase 0/1).

Fase 0, aceitacao: "conexao Firebird provada por SELECT 1".
RNF-05 — o usuario configurado precisa apenas de SELECT geral e UPDATE
em tres colunas de segurados_inc; nada aqui eleva privilegio.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from certgen.config.settings import ConfigFirebird


class ErroConexao(RuntimeError):
    """Falha ao abrir ou consultar o Firebird."""


@contextmanager
def abrir_conexao(cfg: ConfigFirebird) -> Iterator[firebird.driver.Connection]:  # noqa: F821
    """Abre uma conexao read-committed e a fecha ao sair do bloco."""
    if not cfg.completa():
        raise ErroConexao(
            "Configuracao Firebird incompleta: preencha FIREBIRD_HOST, "
            "FIREBIRD_DATABASE, FIREBIRD_USER e FIREBIRD_PASSWORD no .env"
        )
    try:
        from firebird.driver import connect
    except ImportError as exc:  # pragma: no cover - ambiente sem driver
        raise ErroConexao("Pacote firebird-driver nao instalado: pip install -e .") from exc

    try:
        con = connect(cfg.dsn, user=cfg.user, password=cfg.password, charset=cfg.charset)
    except Exception as exc:  # driver lanca varias classes; unificamos
        raise ErroConexao(f"Nao foi possivel conectar em {cfg.dsn}: {exc}") from exc
    try:
        yield con
    finally:
        con.close()


def verificar_conexao(cfg: ConfigFirebird) -> str:
    """Executa SELECT 1 e devolve a versao do servidor. Levanta ErroConexao se falhar."""
    with abrir_conexao(cfg) as con:
        cur = con.cursor()
        cur.execute("SELECT 1 FROM rdb$database")
        (um,) = cur.fetchone()
        if um != 1:
            raise ErroConexao(f"SELECT 1 devolveu {um!r}")
        versao = getattr(con.info, "version", None) or getattr(con.info, "engine_version", "?")
        return f"Firebird {versao} em {cfg.dsn} (charset {cfg.charset})"
