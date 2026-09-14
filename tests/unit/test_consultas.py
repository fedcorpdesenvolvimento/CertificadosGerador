"""RD-17 / RN-06 / RN-07 — carga de queries.sql e composicao de filtros (sem banco)."""

import pytest

from certgen.adapters.firebird.consultas import (
    ConsultaDesconhecida,
    Filtros,
    consulta,
    montar,
    nomes,
)


def test_rd_17_blocos_esperados_existem():
    assert set(nomes()) >= {
        "administradoras", "apolices", "faturas", "certificado_base",
        "endosso_por_fatura", "faturamento", "registrar_link", "existe_segurado",
    }  # fmt: skip


def test_rd_17_bloco_desconhecido_falha():
    with pytest.raises(ConsultaDesconhecida):
        consulta("nao_existe")


def test_rd_02_rd_19_toda_consulta_a_segurados_inc_filtra_status_e_cpf():
    for nome in ("apolices", "faturas", "certificado_base", "existe_segurado"):
        sql = consulta(nome)
        assert "ss.status_seg <> 'C'" in sql, nome
        assert "ss.cpf_cnpj <> ''" in sql, nome


def test_gap_17_join_cob_aux_pela_chave_primaria():
    sql = consulta("certificado_base")
    assert "sicb.endosso = ss.endosso" in sql
    assert "sicb.fatura" not in sql


def test_gap_16_linha_branca_nao_projetada():
    assert "linha_branca" not in consulta("certificado_base").lower()


def test_rn_02_cob_incendio_com_coalesce():
    sql = consulta("certificado_base")
    assert "COALESCE(ss.inc_conteudo, 0) + COALESCE(ss.inc_predio, 0)" in sql


def test_rn_20_cod_0800_com_coalesce_no_abrev():
    assert "COALESCE(pes.abrev, '')" in consulta("certificado_base")


def test_rn_26_projeta_sucursal_pela_fk_de_apolices():
    sql = consulta("certificado_base")
    assert "apo.sucursal" in sql
    assert "apo.cod_seguradora = ss.cod_seguradora" in sql


def test_rd_04_rd_08_projeta_cod_seguradora_abrev_e_cod_cat():
    sql = consulta("certificado_base")
    assert "ss.cod_seguradora" in sql
    assert "pes.abrev" in sql
    assert "en.cod_cat" in sql


def test_rn_07_filtros_opcionais_so_entram_quando_ha_valor():
    f = Filtros().igual("ss.administradora", "0000004691").igual("ss.inicio_vig", None)
    sql, params = f.aplicar("SELECT 1 FROM t WHERE 1=1\n  /*FILTROS*/\nORDER BY 1")
    assert "ss.administradora = ?" in sql
    assert "inicio_vig" not in sql
    assert params == ["0000004691"]


def test_rn_06_valores_nunca_entram_no_sql():
    f = Filtros().igual("ss.certificado", "3082/01/AP 1302'; DROP TABLE x; --")
    sql, params = montar("certificado_base", f)
    assert "DROP" not in sql
    assert params == ["3082/01/AP 1302'; DROP TABLE x; --"]


def test_rn_22_filtro_em_lista():
    f = Filtros().em("fat.apolice", ["4008", "5008"])
    sql, params = f.aplicar("X /*FILTROS*/")
    assert "fat.apolice IN (?, ?)" in sql
    assert params == ["4008", "5008"]


def test_rn_05a_consultas_por_data_fat_partem_de_faturas():
    from datetime import date

    for nome in ("apolices_por_data_fat", "faturas_por_data_fat"):
        sql = consulta(nome)
        assert sql.startswith("SELECT") and "FROM faturas fat" in sql
        assert "fat.data_fat = ?" in sql
        assert "ss.status_seg <> 'C'" in sql and "ss.cpf_cnpj <> ''" in sql  # RD-02, RD-19
    f = Filtros(parametros=[date(2026, 7, 30), "adm", "13008", 1])
    f.igual("ss.inicio_vig", date(2026, 7, 1))
    sql, params = montar("faturas_por_data_fat", f)
    assert "AND ss.inicio_vig = ?)" in sql.replace("\n", "")  # filtro entra dentro do EXISTS
    assert params == [date(2026, 7, 30), "adm", "13008", 1, date(2026, 7, 1)]


def test_rn_05a_filtro_data_fat_usa_exists_em_faturas():
    from datetime import date

    f = Filtros().igual("ss.administradora", "x").data_fat(date(2026, 7, 30))
    sql, params = montar("faturas", f)
    assert "EXISTS (SELECT 1 FROM faturas fat WHERE fat.fatura = ss.fatura" in sql
    assert "fat.data_fat = ?" in sql
    assert params == ["x", date(2026, 7, 30)]
    sql2, params2 = montar("faturas", Filtros().igual("ss.administradora", "x").data_fat(None))
    assert "faturas fat" not in sql2 and params2 == ["x"]


def test_rn_07_filtro_em_consulta_sem_marcador_e_erro():
    with pytest.raises(ValueError):
        Filtros().igual("a", 1).aplicar("SELECT 1")


def test_rn_07_marcador_removido_quando_nao_ha_filtros():
    sql, _ = montar("faturas")
    assert "/*FILTROS*/" not in sql


def test_qry_14_existe_segurado_so_conta_e_nao_filtra_vigencia():
    """RN-35 (14/09/2026) / RF-20: COUNT, sem dados do segurado, sem filtro de vigencia."""
    sql = consulta("existe_segurado")
    assert sql.upper().startswith("SELECT COUNT(*)")
    assert "ss.nome" not in sql and "ss.endereco" not in sql
    assert "inicio_vig" not in sql and "final_vig" not in sql
    assert sql.count("?") == 2  # administradora, cpf_cnpj
