"""Pool de conexoes no modelo EnvioPorto/FedHub — testado com conexao falsa, sem banco."""

import pytest

from certgen.adapters.firebird import conexao
from certgen.config.settings import ConfigFirebird


class CursorFalso:
    def __init__(self, viva):
        self._viva = viva

    def execute(self, sql, params=None):
        if not self._viva():
            raise RuntimeError("conexao morta")

    def fetchone(self):
        return (1,)

    def close(self):
        pass


class ConexaoFalsa:
    def __init__(self):
        self.viva = True
        self.rollbacks = 0
        self.fechada = False

    def cursor(self):
        return CursorFalso(lambda: self.viva)

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.fechada = True


@pytest.fixture
def pool(monkeypatch):
    criadas: list[ConexaoFalsa] = []

    def fabrica(cfg, charset):
        c = ConexaoFalsa()
        criadas.append(c)
        return c

    monkeypatch.setattr(conexao, "_criar_conexao", fabrica)
    conexao.esvaziar_pools()
    conexao.configurar(ConfigFirebird("h", 3050, "db", "u", "p", "WIN1252", pool_size=2))
    yield criadas
    conexao.esvaziar_pools()
    conexao.configurar(None)  # type: ignore[arg-type]


def test_pool_close_devolve_ao_pool_com_rollback_e_reaproveita(pool):
    c1 = conexao.conectar()
    real = c1._conn
    c1.close()
    assert real.rollbacks == 1
    assert real.fechada is False  # nao fechou de verdade
    c2 = conexao.conectar()
    assert c2._conn is real  # reaproveitada
    assert len(pool) == 1


def test_pool_close_duas_vezes_e_inofensivo(pool):
    c = conexao.conectar()
    c.close()
    c.close()
    assert c._conn.rollbacks == 1


def test_pool_conexao_morta_e_descartada_e_outra_criada(pool):
    c1 = conexao.conectar()
    real = c1._conn
    c1.close()
    real.viva = False
    c2 = conexao.conectar()
    assert c2._conn is not real
    assert real.fechada is True
    assert len(pool) == 2


def test_pool_um_por_charset(pool):
    a = conexao.conectar("WIN1252")
    b = conexao.conectar("ASCII")
    a.close()
    b.close()
    assert conexao.conectar("ASCII")._conn is b._conn
    assert conexao.conectar("WIN1252")._conn is a._conn


def test_pool_excedente_e_fechado_de_verdade(pool):
    abertas = [conexao.conectar() for _ in range(3)]  # pool_size=2
    for c in abertas:
        c.close()
    fechadas = [c for c in pool if c.fechada]
    assert len(fechadas) == 1


def test_pool_context_manager_devolve(pool):
    with conexao.conectar() as con:
        real = con._conn
    assert real.rollbacks == 1
    assert conexao.conectar()._conn is real


def test_fase_0_verificar_conexao_executa_select_1(pool):
    msg = conexao.verificar_conexao()
    assert msg.startswith("Firebird")
    assert "h/3050:db" in msg
