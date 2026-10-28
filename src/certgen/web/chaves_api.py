"""Chaves de acesso da API do portal — ADR-09 (decisao do usuario, 28/10/2026).

Substitui a chave unica em CERTGEN_API_KEY (RN-30 original, GAP-24) por um cadastro
no mesmo SQLite da tela (ADR-08): uma chave por **cliente integrador**, com a lista de
administradoras que ela pode consultar (escopo), lista opcional de IPs de origem e
revogacao imediata. O ADMIN cria e revoga pela tela; o texto da chave aparece UMA vez.

Seguranca:
- a chave tem 256 bits (`secrets.token_urlsafe(32)`); o banco guarda so o SHA-256,
  como as sessoes. Vazamento do banco nao entrega chaves;
- a busca e pelo hash e a comparacao final em tempo constante (`hmac.compare_digest`);
- `prefixo` (8 primeiros caracteres) identifica a chave em logs e na tela sem revelar
  o segredo (RNF-13);
- `administradoras` vazia = nenhuma; `todas = 1` libera qualquer administradora
  (caso do portal multi-tenant). Fora do escopo = 403 na API;
- `ips` vazia = qualquer origem; preenchida = so aquelas (RN-30 revisto).

Por que nao no Firebird: RNF-05 (so tres colunas de segurados_inc sao escritas).
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import secrets
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chaves_api (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  nome            TEXT NOT NULL,
  prefixo         TEXT NOT NULL,
  chave_hash      TEXT NOT NULL UNIQUE,
  administradoras TEXT NOT NULL DEFAULT '[]',
  todas           INTEGER NOT NULL DEFAULT 0,
  ips             TEXT NOT NULL DEFAULT '[]',
  ativa           INTEGER NOT NULL DEFAULT 1,
  criada_em       TEXT NOT NULL,
  criada_por      INTEGER,
  revogada_em     TEXT,
  ultimo_uso      TEXT,
  ultimo_ip       TEXT
);
"""

TAM_PREFIXO = 8


class ChaveInvalida(ValueError):
    """Dado recusado pelo cadastro."""


def _agora() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def hash_chave(chave: str) -> str:
    return hashlib.sha256(chave.encode()).hexdigest()


def gerar_chave() -> str:
    """256 bits, URL-safe, sem caracteres ambiguos de copia (ADR-09)."""
    return "fc_" + secrets.token_urlsafe(32)


def normalizar_administradoras(valores: object) -> list[str]:
    """Codigos CHAR(10) com zeros a esquerda; vazio e repetido descartados."""
    if not isinstance(valores, list | tuple):
        raise ChaveInvalida("administradoras deve ser uma lista de codigos")
    saida: list[str] = []
    for v in valores:
        codigo = str(v).strip()
        if not codigo:
            continue
        if not codigo.isdigit() or len(codigo) > 10:
            raise ChaveInvalida(f"codigo de administradora invalido: {codigo!r}")
        codigo = codigo.zfill(10)
        if codigo not in saida:
            saida.append(codigo)
    return saida


def normalizar_ips(valores: object) -> list[str]:
    """IPs ou redes CIDR validos; vazio = qualquer origem."""
    if not isinstance(valores, list | tuple):
        raise ChaveInvalida("ips deve ser uma lista")
    saida: list[str] = []
    for v in valores:
        texto = str(v).strip()
        if not texto:
            continue
        try:
            rede = ipaddress.ip_network(texto, strict=False)
        except ValueError as exc:
            raise ChaveInvalida(f"IP ou rede invalido: {texto!r}") from exc
        if str(rede) not in saida:
            saida.append(str(rede))
    return saida


@dataclass(frozen=True)
class ChaveApi:
    id: int
    nome: str
    prefixo: str
    administradoras: tuple[str, ...]
    todas: bool
    ips: tuple[str, ...]
    ativa: bool
    criada_em: str
    criada_por: int | None
    revogada_em: str | None
    ultimo_uso: str | None
    ultimo_ip: str | None

    def permite_administradora(self, codigo: str) -> bool:
        return self.todas or codigo.strip().zfill(10) in self.administradoras

    def permite_ip(self, ip: str | None) -> bool:
        if not self.ips:
            return True
        if not ip:
            return False
        try:
            endereco = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return any(endereco in ipaddress.ip_network(rede) for rede in self.ips)

    def publico(self) -> dict:
        """O que vai para a tela: nunca o hash nem a chave."""
        return {
            "id": self.id,
            "nome": self.nome,
            "prefixo": self.prefixo,
            "administradoras": list(self.administradoras),
            "todas": self.todas,
            "ips": list(self.ips),
            "ativa": self.ativa,
            "criada_em": self.criada_em,
            "criada_por": self.criada_por,
            "revogada_em": self.revogada_em,
            "ultimo_uso": self.ultimo_uso,
            "ultimo_ip": self.ultimo_ip,
        }


def _linha(li: sqlite3.Row) -> ChaveApi:
    return ChaveApi(
        id=li["id"],
        nome=li["nome"],
        prefixo=li["prefixo"],
        administradoras=tuple(json.loads(li["administradoras"])),
        todas=bool(li["todas"]),
        ips=tuple(json.loads(li["ips"])),
        ativa=bool(li["ativa"]),
        criada_em=li["criada_em"],
        criada_por=li["criada_por"],
        revogada_em=li["revogada_em"],
        ultimo_uso=li["ultimo_uso"],
        ultimo_ip=li["ultimo_ip"],
    )


class RepositorioChaves:
    """Acesso ao SQLite de chaves. Mesmo arquivo dos usuarios (CERTGEN_USUARIOS_DB);
    conexao propria com trava, como RepositorioUsuarios."""

    def __init__(self, caminho: Path | str) -> None:
        self.caminho = Path(caminho)
        if str(self.caminho) != ":memory:":
            self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._con = sqlite3.connect(str(self.caminho), check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        with self._tx() as con:
            if str(self.caminho) != ":memory:":
                con.execute("PRAGMA journal_mode = WAL")
            con.executescript(_SCHEMA)

    def fechar(self) -> None:
        with self._lock:
            self._con.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._con
                self._con.commit()
            except Exception:
                self._con.rollback()
                raise

    # ----------------------------------------------------------------- cadastro
    def listar(self) -> list[ChaveApi]:
        with self._tx() as con:
            linhas = con.execute(
                "SELECT * FROM chaves_api ORDER BY ativa DESC, nome COLLATE NOCASE"
            ).fetchall()
        return [_linha(li) for li in linhas]

    def obter(self, chave_id: int) -> ChaveApi | None:
        with self._tx() as con:
            li = con.execute("SELECT * FROM chaves_api WHERE id = ?", (chave_id,)).fetchone()
        return _linha(li) if li else None

    def quantidade_ativas(self) -> int:
        with self._tx() as con:
            (n,) = con.execute("SELECT count(*) FROM chaves_api WHERE ativa = 1").fetchone()
        return int(n)

    def criar(
        self,
        nome: str,
        administradoras: list[str],
        *,
        todas: bool = False,
        ips: list[str] | None = None,
        criada_por: int | None = None,
    ) -> tuple[ChaveApi, str]:
        """Devolve (registro, chave em texto). O texto so existe neste retorno."""
        nome = (nome or "").strip()
        if len(nome) < 2:
            raise ChaveInvalida("informe o nome do cliente (minimo 2 caracteres)")
        adms = normalizar_administradoras(administradoras)
        if not todas and not adms:
            raise ChaveInvalida("informe ao menos uma administradora ou marque 'todas'")
        lista_ips = normalizar_ips(ips or [])
        chave = gerar_chave()
        with self._tx() as con:
            cur = con.execute(
                "INSERT INTO chaves_api (nome, prefixo, chave_hash, administradoras, todas, ips,"
                " criada_em, criada_por) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (nome, chave[:TAM_PREFIXO], hash_chave(chave), json.dumps(adms), int(todas),
                 json.dumps(lista_ips), _agora(), criada_por),
            )  # fmt: skip
            novo_id = int(cur.lastrowid or 0)
        registro = self.obter(novo_id)
        assert registro is not None
        return registro, chave

    def atualizar(
        self, chave_id: int, nome: str, administradoras: list[str], *, todas: bool, ips: list[str]
    ) -> ChaveApi:
        nome = (nome or "").strip()
        if len(nome) < 2:
            raise ChaveInvalida("informe o nome do cliente (minimo 2 caracteres)")
        adms = normalizar_administradoras(administradoras)
        if not todas and not adms:
            raise ChaveInvalida("informe ao menos uma administradora ou marque 'todas'")
        lista_ips = normalizar_ips(ips)
        with self._tx() as con:
            con.execute(
                "UPDATE chaves_api SET nome = ?, administradoras = ?, todas = ?, ips = ?"
                " WHERE id = ?",
                (nome, json.dumps(adms), int(todas), json.dumps(lista_ips), chave_id),
            )
        registro = self.obter(chave_id)
        if registro is None:
            raise ChaveInvalida("chave nao encontrada")
        return registro

    def revogar(self, chave_id: int) -> None:
        """Irreversivel: a chave deixa de autenticar na hora. Para voltar, cria-se outra."""
        with self._tx() as con:
            con.execute(
                "UPDATE chaves_api SET ativa = 0, revogada_em = ? WHERE id = ? AND ativa = 1",
                (_agora(), chave_id),
            )

    # -------------------------------------------------------------- autenticacao
    def autenticar(self, chave: str | None) -> ChaveApi | None:
        """None quando a chave nao existe ou foi revogada. Busca por hash; comparacao
        final em tempo constante (RN-30)."""
        if not chave:
            return None
        alvo = hash_chave(chave)
        with self._tx() as con:
            li = con.execute(
                "SELECT * FROM chaves_api WHERE chave_hash = ? AND ativa = 1", (alvo,)
            ).fetchone()
        if li is None or not hmac.compare_digest(li["chave_hash"], alvo):
            return None
        return _linha(li)

    def registrar_uso(self, chave_id: int, ip: str | None) -> None:
        with self._tx() as con:
            con.execute(
                "UPDATE chaves_api SET ultimo_uso = ?, ultimo_ip = ? WHERE id = ?",
                (_agora(), ip, chave_id),
            )
