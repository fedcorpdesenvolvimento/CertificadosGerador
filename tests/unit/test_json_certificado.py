"""RD-10..RD-15, RD-23, RD-25 — serializacao e validacao do JSON (sem banco)."""

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from certgen.adapters.firebird.repositorio import RepositorioFirebird
from certgen.domain.certificado import ChaveLote
from certgen.serialize.json_certificado import (
    CAMINHO_SCHEMA,
    JsonInvalido,
    MetaEmissao,
    certificado_para_dict,
    erros_de_validacao,
    gravar_json,
    lote_para_dict,
    serializar,
    validar,
)
from tests.unit.test_repositorio_mapeamento import LINHA_13008

BRT = timezone(timedelta(hours=-3))
AGORA = datetime(2026, 9, 3, 14, 22, 7, tzinfo=BRT)


@pytest.fixture(scope="module")
def cert():
    return RepositorioFirebird()._montar(LINHA_13008)


@pytest.fixture
def meta():
    return MetaEmissao(
        gerado_em=AGORA,
        nome_pdf="0_33016330725_0004_13008_CF1DI-AP602_380819.pdf",
        pasta_destino="0000001192/072026",
        exibe_premio=True,
    )


@pytest.fixture
def doc(cert, meta):
    return certificado_para_dict(cert, meta)


def test_rd_15_schema_existe_e_e_valido():
    assert CAMINHO_SCHEMA.is_file()
    schema = json.loads(CAMINHO_SCHEMA.read_text(encoding="utf-8"))
    assert schema["$schema"].endswith("2020-12/schema")


def test_rd_10_documento_da_referencia_valida_no_schema(doc):
    assert erros_de_validacao(doc) == []


def test_rd_25_bloco_arquivo(doc):
    assert doc["arquivo"] == {
        "pdf": "0_33016330725_0004_13008_CF1DI-AP602_380819.pdf",
        "pasta_destino": "0000001192/072026",
        "link": None,
    }


def test_adr_06_meta_template_unico_com_flag_faz_tudo(doc):
    assert doc["_meta"]["template"] == "demonstrativo_v1"
    assert doc["_meta"]["faz_tudo_lar"] is True
    assert doc["_meta"]["versao_schema"] == "1.0"
    assert doc["_meta"]["gerado_em"] == "2026-09-03T14:22:07-03:00"


def test_rn_21_data_emissao_e_a_data_de_geracao(doc):
    assert doc["certificado"]["data_emissao"] == "2026-09-03"


def test_rd_11_onze_coberturas_na_ordem_com_nao_contratadas(doc):
    cobs = doc["coberturas"]
    assert len(cobs) == 11
    assert cobs[2] == {
        "codigo": "COB_INCENDIO", "nome": "Cobertura Incendio",
        "importancia_segurada": "100000.00", "contratada": True, "derivada": True,
    }  # fmt: skip
    nao = [c for c in cobs if not c["contratada"]]
    assert all(c["importancia_segurada"] is None for c in nao)
    assert len(nao) == 6


def test_rd_05_dinheiro_como_string_decimal(doc):
    assert doc["premio"] == {"valor_total": "18.90", "moeda": "BRL", "impresso_no_pdf": True}
    texto = serializar(doc)
    assert '"valor_total": "18.90"' in texto


def test_rd_06_datas_iso(doc):
    assert doc["vigencia"] == {"inicio": "2026-07-01", "fim": "2026-07-31"}


def test_rd_13_nulos_aparecem_como_null_nao_omitidos(doc):
    assert doc["administradora"]["abreviacao"] is None
    assert doc["contrato"]["codigo_pedido_porto"] is None
    assert doc["contrato"]["plano"] is None  # RN-23
    assert '"abreviacao": null' in serializar(doc)


def test_rd_23_avisos_no_meta(doc):
    codigos = {a["codigo"] for a in doc["_meta"]["avisos"]}
    assert codigos == {"ABREV_ADM_AUSENTE", "PORTAL_AUSENTE"}


def test_rn_25_rn_26_contrato_com_susep_e_sucursal(doc):
    assert doc["contrato"]["susep_corretora"] == "00000202049583"
    assert doc["contrato"]["sucursal"] == "RJ"
    assert doc["contrato"]["estipulante"] == "FEDCORP ADMINISTRADORA DE BENEFICIOS LTDA"
    assert doc["contrato"]["apolice"] == {
        "codigo": "13008", "seq": 0, "numero_seguradora": "40150116/R-ESP", "cod_seguradora": "1",
    }  # fmt: skip


def test_rn_20_cod_0800_e_rd_12_documento(doc):
    assert doc["certificado"]["cod_0800"] == "CF1DI/AP.602"
    assert doc["segurado"]["documento"] == {
        "tipo": "CPF", "numero": "33016330725", "formatado": "330.163.307-25",
    }  # fmt: skip


def test_rd_10_origem_traz_a_chave_completa(doc):
    assert doc["_origem"]["chave"] == {
        "administradora": "0000001192", "apolice": "13008", "seq": 0, "fatura": 380819,
        "certificado": "CF1DI/AP.602", "cpf_cnpj": "33016330725",
    }  # fmt: skip


def test_rn_21_gerado_em_sem_fuso_e_erro(cert, meta):
    sem_fuso = MetaEmissao(datetime(2026, 9, 3), meta.nome_pdf, meta.pasta_destino, True)
    with pytest.raises(ValueError):
        certificado_para_dict(cert, sem_fuso)


def test_rd_15_documento_invalido_nao_e_gravado(doc, tmp_path):
    doc["coberturas"].pop()  # 10 coberturas viola RD-11
    doc["premio"]["valor_total"] = 18.9  # float viola RD-05
    alvo = tmp_path / "x.json"
    with pytest.raises(JsonInvalido) as exc:
        gravar_json(doc, alvo)
    assert not alvo.exists()
    assert any("coberturas" in e for e in exc.value.erros)
    assert any("valor_total" in e for e in exc.value.erros)


def test_rd_15_campo_estranho_e_rejeitado(doc):
    doc["segurado"]["email"] = "x@y"  # RD-10: nada alem do que o PDF imprime
    with pytest.raises(JsonInvalido):
        validar(doc)


def test_rd_15_gravar_valida_e_escreve_utf8(doc, tmp_path):
    doc["administradora"]["nome"] = "IMODATA ADM DE IMOVEIS E SERVIÇOS"
    destino, colidiu = gravar_json(doc, tmp_path / "a" / "b.json")
    assert destino == tmp_path / "a" / "b.json"
    assert colidiu is False
    assert "SERVIÇOS" in destino.read_text(encoding="utf-8")
    assert json.loads(destino.read_text(encoding="utf-8")) == doc


def test_rn_13_colisao_recebe_sufixo_e_nao_sobrescreve(doc, tmp_path):
    alvo = tmp_path / "c.json"
    alvo.write_text("original", encoding="utf-8")
    destino, colidiu = gravar_json(doc, alvo)
    assert colidiu is True
    assert destino == tmp_path / "c (1).json"
    assert alvo.read_text(encoding="utf-8") == "original"


def test_rnf_08_serializacao_deterministica(doc):
    assert serializar(doc) == serializar(json.loads(serializar(doc)))


def test_rd_14_envelope_consolidado_remove_meta_dos_itens(doc):
    lote = ChaveLote("0000001192", "13008", 1, 380819)
    env = lote_para_dict([doc, doc], lote, "072026", "certificados_13008_1_380819_x.pdf")
    assert env["_meta"] == {"quantidade": 2, "arquivo_pdf": "certificados_13008_1_380819_x.pdf"}
    assert env["lote"]["competencia"] == "072026"
    assert all("_meta" not in c for c in env["certificados"])
    assert env["certificados"][0]["arquivo"]["pdf"].endswith(".pdf")


def test_utc_tambem_e_aceito(cert, meta):
    d = certificado_para_dict(
        cert, MetaEmissao(AGORA.astimezone(UTC), meta.nome_pdf, meta.pasta_destino, True)
    )
    assert d["_meta"]["gerado_em"].endswith("+00:00")
    assert erros_de_validacao(d) == []


def test_schema_path_dentro_de_docs():
    assert CAMINHO_SCHEMA.relative_to(Path(CAMINHO_SCHEMA).parents[2]).parts[0] == "docs"
