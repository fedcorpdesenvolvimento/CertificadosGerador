"""Ponto unico de conexao com o Firebird — com pool.

Modelo copiado de U:\\--2021\\04-EnvioPorto\\db.py (03/09/2026), que segue o
FedHub-Backend (src/shared/database/connection_firebird.py):

- driver `fdb` (o servidor e Firebird 2.5; `firebird-driver` exige 3+);
- conexoes ociosas ficam retidas num pool por processo e sao reaproveitadas;
- `close()` do proxy devolve ao pool (com rollback) em vez de fechar;
- ha um pool por charset, porque o charset e fixado na abertura;
- conexao ociosa e validada com SELECT 1 antes de ser reutilizada.

Ninguem fora deste modulo chama `fdb.connect` (mesma regra do EnvioPorto).
O repositorio Firebird usa `conectar()`; o dominio nao conhece nada disto (ADR-01).

RNF-05 — o usuario configurado precisa apenas de SELECT geral e UPDATE em tres
colunas de segurados_inc; nada aqui eleva privilegio.
"""

from __future__ import annotations

import queue
import threading
from typing import Any

from certgen.config.settings import Config, ConfigFirebird


class ErroConexao(RuntimeError):
    """Falha ao abrir ou consultar o Firebird."""


# um pool (LifoQueue) por charset; criado sob demanda
_pools: dict[str, queue.LifoQueue] = {}
_pools_lock = threading.Lock()
_config: ConfigFirebird | None = None


def configurar(cfg: ConfigFirebird) -> None:
    """Fixa a configuracao usada por `conectar()`. Sem isto, le do ambiente."""
    global _config
    _config = cfg


def _configuracao() -> ConfigFirebird:
    global _config
    if _config is None:
        cfg = Config.do_ambiente().firebird
        if cfg is None:
            raise ErroConexao("CERTGEN_REPOSITORIO nao e 'firebird'; nao ha conexao a abrir")
        _config = cfg
    return _config


def _pool_do_charset(charset: str) -> queue.LifoQueue:
    with _pools_lock:
        if charset not in _pools:
            _pools[charset] = queue.LifoQueue(maxsize=_configuracao().pool_size)
        return _pools[charset]


class ConexaoPool:
    """Proxy de conexao do pool: close() devolve ao pool em vez de fechar.

    A devolucao faz rollback para garantir que nenhuma transacao pendente
    vaze para o proximo usuario da conexao.
    """

    def __init__(self, conn: Any, charset: str) -> None:
        self._conn = conn
        self._charset = charset
        self._fechada = False

    def close(self) -> None:
        if self._fechada:
            return
        self._fechada = True
        _devolver(self._conn, self._charset)

    def __getattr__(self, nome: str) -> Any:
        return getattr(self._conn, nome)

    def __enter__(self) -> ConexaoPool:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _criar_conexao(cfg: ConfigFirebird, charset: str) -> Any:
    try:
        import fdb
    except ImportError as exc:  # pragma: no cover - ambiente sem driver
        raise ErroConexao("Pacote fdb nao instalado: pip install -e .") from exc
    try:
        return fdb.connect(
            host=cfg.host,
            port=cfg.port,
            database=cfg.database,
            user=cfg.user,
            password=cfg.password,
            charset=charset,
        )
    except Exception as exc:  # fdb lanca varias classes; unificamos
        raise ErroConexao(f"Nao foi possivel conectar em {cfg.dsn}: {exc}") from exc


def _validar(conn: Any) -> bool:
    """Confere se a conexao ociosa ainda esta viva antes de reutiliza-la."""
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM RDB$DATABASE")
        cur.fetchone()
        cur.close()
        return True
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        return False


def _devolver(conn: Any, charset: str) -> None:
    try:
        conn.rollback()
        _pool_do_charset(charset).put_nowait(conn)
    except queue.Full:
        conn.close()
    except Exception:
        try:
            conn.close()
        except Exception:
            pass


def conectar(charset: str | None = None) -> ConexaoPool:
    """Abre (ou reaproveita do pool) uma conexao com o banco.

    charset: sobrepoe o FB_CHARSET do .env quando necessario. O objeto devolvido
    se comporta como a conexao fdb; close() devolve a conexao ao pool.
    """
    cfg = _configuracao()
    charset = charset or cfg.charset
    pool = _pool_do_charset(charset)
    while True:
        try:
            conn = pool.get_nowait()
        except queue.Empty:
            break
        if _validar(conn):
            return ConexaoPool(conn, charset)
    return ConexaoPool(_criar_conexao(cfg, charset), charset)


def esvaziar_pools() -> None:
    """Fecha de verdade todas as conexoes retidas (encerramento do processo, testes)."""
    with _pools_lock:
        for pool in _pools.values():
            while True:
                try:
                    conn = pool.get_nowait()
                except queue.Empty:
                    break
                try:
                    conn.close()
                except Exception:
                    pass
        _pools.clear()


def verificar_conexao(cfg: ConfigFirebird | None = None) -> str:
    """Fase 0 — SELECT 1 e versao do servidor. Levanta ErroConexao se falhar."""
    if cfg is not None:
        configurar(cfg)
    cfg = _configuracao()
    with conectar() as con:
        cur = con.cursor()
        cur.execute("SELECT 1 FROM RDB$DATABASE")
        (um,) = cur.fetchone()
        cur.close()
        if um != 1:
            raise ErroConexao(f"SELECT 1 devolveu {um!r}")
        versao = getattr(con, "server_version", None) or getattr(con, "version", "?")
        return f"Firebird {versao} em {cfg.dsn} (charset {cfg.charset}, pool {cfg.pool_size})"
