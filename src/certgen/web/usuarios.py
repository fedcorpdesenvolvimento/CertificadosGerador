"""Usuarios e sessoes da tela — ADR-08 (decisao do usuario, 23/10/2026).

Modelo copiado do Sistema de Sinistros FedCorp (`db/schema.sql`, tabela `usuarios`;
`src/auth.js`): e-mail como login, hash bcrypt, perfil, ativo (cancelar = desativar),
`trocar_senha` para senha temporaria, `ultimo_login`.

Por que SQLite e nao o Firebird: RNF-05 limita a escrita no FATURA.GDB a tres
colunas de `segurados_inc`; criar tabelas la esta fora do escopo. O arquivo fica em
`CERTGEN_USUARIOS_DB` (padrao `dados/usuarios.sqlite` na raiz; no Render, um disco
persistente). O dominio nao conhece nada disto (ADR-01): e infraestrutura da tela.

Sessoes sao do lado do servidor (tabela `sessoes`): o cookie leva so um token
aleatorio de 256 bits e o banco guarda o SHA-256 dele. Desativar o usuario, trocar
a senha ou resetar apaga as sessoes na hora, como no Sinistros.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

PERFIS = {"ADMIN": "Administrador do Sistema", "OPERADOR": "Operador"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  nome          TEXT NOT NULL,
  email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
  senha_hash    TEXT NOT NULL,
  perfil        TEXT NOT NULL CHECK (perfil IN ('ADMIN', 'OPERADOR')),
  ativo         INTEGER NOT NULL DEFAULT 1,
  trocar_senha  INTEGER NOT NULL DEFAULT 0,
  ultimo_login  TEXT,
  criado_em     TEXT NOT NULL,
  atualizado_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessoes (
  token_hash  TEXT PRIMARY KEY,
  usuario_id  INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
  criada_em   TEXT NOT NULL,
  expira_em   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sessoes_usuario ON sessoes(usuario_id);
"""


class UsuarioInvalido(ValueError):
    """Dado recusado pelo cadastro (e-mail repetido, perfil desconhecido...)."""


@dataclass(frozen=True)
class Usuario:
    id: int
    nome: str
    email: str
    perfil: str
    ativo: bool
    trocar_senha: bool
    ultimo_login: str | None
    criado_em: str

    @property
    def admin(self) -> bool:
        return self.perfil == "ADMIN"

    @property
    def perfil_nome(self) -> str:
        return PERFIS.get(self.perfil, self.perfil)

    def publico(self) -> dict:
        """O que vai para a tela: nunca o hash."""
        return {
            "id": self.id,
            "nome": self.nome,
            "email": self.email,
            "perfil": self.perfil,
            "perfil_nome": PERFIS.get(self.perfil, self.perfil),
            "ativo": self.ativo,
            "trocar_senha": self.trocar_senha,
            "ultimo_login": self.ultimo_login,
            "criado_em": self.criado_em,
        }


def _agora() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _linha_para_usuario(li: sqlite3.Row) -> Usuario:
    return Usuario(
        id=li["id"],
        nome=li["nome"],
        email=li["email"],
        perfil=li["perfil"],
        ativo=bool(li["ativo"]),
        trocar_senha=bool(li["trocar_senha"]),
        ultimo_login=li["ultimo_login"],
        criado_em=li["criado_em"],
    )


class RepositorioUsuarios:
    """Acesso ao SQLite de usuarios/sessoes. Uma conexao por repositorio, com trava:
    os endpoints da tela sao sincronos e rodam no threadpool do Starlette."""

    def __init__(self, caminho: Path | str) -> None:
        self.caminho = Path(caminho)
        if str(self.caminho) != ":memory:":
            self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._con = sqlite3.connect(str(self.caminho), check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        with self._tx() as con:
            con.execute("PRAGMA foreign_keys = ON")
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

    # ---------------------------------------------------------------- usuarios
    def listar(self) -> list[Usuario]:
        with self._tx() as con:
            linhas = con.execute("SELECT * FROM usuarios ORDER BY nome COLLATE NOCASE").fetchall()
        return [_linha_para_usuario(li) for li in linhas]

    def obter(self, usuario_id: int) -> Usuario | None:
        with self._tx() as con:
            li = con.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
        return _linha_para_usuario(li) if li else None

    def obter_por_email(self, email: str) -> Usuario | None:
        with self._tx() as con:
            li = con.execute(
                "SELECT * FROM usuarios WHERE email = ? COLLATE NOCASE", (email.strip().lower(),)
            ).fetchone()
        return _linha_para_usuario(li) if li else None

    def hash_da_senha(self, usuario_id: int) -> str | None:
        with self._tx() as con:
            li = con.execute(
                "SELECT senha_hash FROM usuarios WHERE id = ?", (usuario_id,)
            ).fetchone()
        return li["senha_hash"] if li else None

    def existe_admin(self) -> bool:
        with self._tx() as con:
            li = con.execute(
                "SELECT 1 FROM usuarios WHERE perfil = 'ADMIN' AND ativo = 1 LIMIT 1"
            ).fetchone()
        return li is not None

    def quantidade_admins_ativos(self) -> int:
        with self._tx() as con:
            (n,) = con.execute(
                "SELECT count(*) FROM usuarios WHERE perfil = 'ADMIN' AND ativo = 1"
            ).fetchone()
        return int(n)

    def criar(
        self, nome: str, email: str, senha_hash: str, perfil: str, *, trocar_senha: bool
    ) -> Usuario:
        if perfil not in PERFIS:
            raise UsuarioInvalido(f"perfil desconhecido: {perfil}")
        agora = _iso(_agora())
        try:
            with self._tx() as con:
                cur = con.execute(
                    "INSERT INTO usuarios (nome, email, senha_hash, perfil, trocar_senha,"
                    " criado_em, atualizado_em) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (nome.strip(), email.strip().lower(), senha_hash, perfil,
                     int(trocar_senha), agora, agora),
                )  # fmt: skip
                novo_id = cur.lastrowid
        except sqlite3.IntegrityError as exc:
            raise UsuarioInvalido("ja existe usuario com este e-mail") from exc
        usuario = self.obter(int(novo_id))
        assert usuario is not None
        return usuario

    def atualizar(self, usuario_id: int, nome: str, email: str, perfil: str) -> Usuario:
        if perfil not in PERFIS:
            raise UsuarioInvalido(f"perfil desconhecido: {perfil}")
        try:
            with self._tx() as con:
                con.execute(
                    "UPDATE usuarios SET nome = ?, email = ?, perfil = ?, atualizado_em = ?"
                    " WHERE id = ?",
                    (nome.strip(), email.strip().lower(), perfil, _iso(_agora()), usuario_id),
                )
        except sqlite3.IntegrityError as exc:
            raise UsuarioInvalido("ja existe usuario com este e-mail") from exc
        usuario = self.obter(usuario_id)
        if usuario is None:
            raise UsuarioInvalido("usuario nao encontrado")
        return usuario

    def definir_ativo(self, usuario_id: int, ativo: bool) -> None:
        """Cancelar = desativar; desativar derruba as sessoes na hora (Sinistros)."""
        with self._tx() as con:
            con.execute(
                "UPDATE usuarios SET ativo = ?, atualizado_em = ? WHERE id = ?",
                (int(ativo), _iso(_agora()), usuario_id),
            )
            if not ativo:
                con.execute("DELETE FROM sessoes WHERE usuario_id = ?", (usuario_id,))

    def definir_senha(
        self,
        usuario_id: int,
        senha_hash: str,
        *,
        trocar_senha: bool,
        manter_token: str | None = None,
    ) -> None:
        """Grava o hash novo e encerra as outras sessoes do usuario (a atual pode ficar)."""
        with self._tx() as con:
            con.execute(
                "UPDATE usuarios SET senha_hash = ?, trocar_senha = ?, atualizado_em = ?"
                " WHERE id = ?",
                (senha_hash, int(trocar_senha), _iso(_agora()), usuario_id),
            )
            if manter_token:
                con.execute(
                    "DELETE FROM sessoes WHERE usuario_id = ? AND token_hash <> ?",
                    (usuario_id, _hash_token(manter_token)),
                )
            else:
                con.execute("DELETE FROM sessoes WHERE usuario_id = ?", (usuario_id,))

    def registrar_login(self, usuario_id: int) -> None:
        with self._tx() as con:
            con.execute(
                "UPDATE usuarios SET ultimo_login = ? WHERE id = ?", (_iso(_agora()), usuario_id)
            )

    # ----------------------------------------------------------------- sessoes
    def criar_sessao(self, usuario_id: int, horas: int) -> str:
        """Devolve o token (so ele vai no cookie); o banco guarda o SHA-256."""
        token = secrets.token_urlsafe(32)
        agora = _agora()
        with self._tx() as con:
            con.execute(
                "INSERT INTO sessoes (token_hash, usuario_id, criada_em, expira_em)"
                " VALUES (?, ?, ?, ?)",
                (_hash_token(token), usuario_id, _iso(agora), _iso(agora + timedelta(hours=horas))),
            )
            # higiene: sessoes vencidas de qualquer usuario
            con.execute("DELETE FROM sessoes WHERE expira_em < ?", (_iso(agora),))
        return token

    def usuario_da_sessao(self, token: str | None) -> Usuario | None:
        """None se o token nao existe, venceu ou o usuario foi desativado."""
        if not token:
            return None
        with self._tx() as con:
            li = con.execute(
                "SELECT u.*, s.expira_em FROM sessoes s JOIN usuarios u ON u.id = s.usuario_id"
                " WHERE s.token_hash = ?",
                (_hash_token(token),),
            ).fetchone()
            if li is None:
                return None
            if li["expira_em"] < _iso(_agora()) or not li["ativo"]:
                con.execute("DELETE FROM sessoes WHERE token_hash = ?", (_hash_token(token),))
                return None
        return _linha_para_usuario(li)

    def encerrar_sessao(self, token: str | None) -> None:
        if not token:
            return
        with self._tx() as con:
            con.execute("DELETE FROM sessoes WHERE token_hash = ?", (_hash_token(token),))

    def encerrar_sessoes_do_usuario(self, usuario_id: int) -> None:
        with self._tx() as con:
            con.execute("DELETE FROM sessoes WHERE usuario_id = ?", (usuario_id,))

    def quantidade_sessoes(self, usuario_id: int) -> int:
        with self._tx() as con:
            (n,) = con.execute(
                "SELECT count(*) FROM sessoes WHERE usuario_id = ?", (usuario_id,)
            ).fetchone()
        return int(n)
