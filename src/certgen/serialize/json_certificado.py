"""RD-10..RD-15, RD-23, RD-25 — Certificado -> dict -> JSON Schema -> arquivo.

Principio (secao 9): o JSON nao e um dump da consulta, e o certificado modelado
como dado. Contem tudo que o PDF imprime, mais `_meta`, `_origem` e `arquivo`.

- RD-05/RD-06: dinheiro como string decimal, datas ISO 8601.
- RD-11: as 11 coberturas sempre presentes.
- RD-13: nulo e `null`, nunca omitido nem "".
- RD-15: validado contra docs/schema/certificado-1.0.schema.json ANTES da
  escrita; JSON invalido nao e gravado.
- RD-25: bloco `arquivo` {pdf, pasta_destino, link}.
- RN-13: nunca sobrescreve silenciosamente.
- ADR-06: `_meta.template` = "demonstrativo_v1", com `faz_tudo_lar`.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from certgen import __version__
from certgen.config.settings import RAIZ_PROJETO
from certgen.domain.certificado import ESTIPULANTE, Certificado, ChaveLote
from certgen.domain.dinheiro import para_json
from certgen.domain.nomes_arquivo import resolver_colisao

VERSAO_SCHEMA = "1.0"
TEMPLATE = "demonstrativo_v1"  # ADR-06
CENTRAL_ATENDIMENTO = "0800 770 4362"  # rodape do PDF de referencia
CENTRAL_FEDCORP = "0800 251 6001"
CAMINHO_SCHEMA = RAIZ_PROJETO / "docs" / "schema" / f"certificado-{VERSAO_SCHEMA}.schema.json"


class JsonInvalido(ValueError):
    """RD-15 — o documento nao passa no schema. Nao e gravado; o certificado conta como falha."""

    def __init__(self, erros: list[str]) -> None:
        self.erros = erros
        resumo = "; ".join(erros[:5]) + (" ..." if len(erros) > 5 else "")
        super().__init__(f"JSON invalido: {resumo}")


@dataclass(frozen=True)
class MetaEmissao:
    """O que a serializacao precisa saber e que nao esta no Certificado."""

    gerado_em: datetime  # com fuso; RN-21
    nome_pdf: str  # RN-11
    pasta_destino: str  # RN-19 — {administradora}/{competencia}
    exibe_premio: bool  # RF-10
    modo_conexao: str = "firebird-local"  # ADR-01
    link: str | None = None  # RD-25 — preenchido na Fase 7
    faz_tudo_lar: bool | None = None  # ADR-06 — escolha do operador; None = derivacao RN-18


def _data(valor) -> str | None:
    return None if valor is None else valor.isoformat()


def certificado_para_dict(cert: Certificado, meta: MetaEmissao) -> dict:
    """RD-10 — projecao completa do certificado."""
    if meta.gerado_em.tzinfo is None:
        raise ValueError("gerado_em deve ter fuso horario (RN-21 / RNF-08)")
    faz_tudo = cert.faz_tudo_lar_efetivo(meta.faz_tudo_lar)
    avisos = cert.todos_avisos()
    if (extra := cert.aviso_faz_tudo_lar(meta.faz_tudo_lar)) is not None:
        avisos.append(extra)
    return {
        "_meta": {
            "versao_schema": VERSAO_SCHEMA,
            "gerado_em": meta.gerado_em.isoformat(timespec="seconds"),
            "gerado_por": f"gerador-certificados/{__version__}",
            "template": TEMPLATE,
            "faz_tudo_lar": faz_tudo,
            "modo_conexao": meta.modo_conexao,
            "avisos": [a.para_dict() for a in avisos],
        },
        "arquivo": {
            "pdf": meta.nome_pdf,
            "pasta_destino": meta.pasta_destino,
            "link": meta.link,
        },
        "certificado": {
            "numero": cert.numero,
            "cod_0800": cert.cod_0800,
            "data_emissao": meta.gerado_em.date().isoformat(),
        },
        "produto": {**cert.produto.para_dict(), "faz_tudo_lar": faz_tudo},
        "contrato": {
            "apolice": {
                "codigo": cert.contrato.apolice,
                "seq": cert.contrato.seq,
                "numero_seguradora": cert.contrato.apolice_seguradora,
                "cod_seguradora": cert.contrato.cod_seguradora,
                "seguradora": cert.contrato.seguradora.nome if cert.contrato.seguradora else None,
            },
            "fatura": cert.contrato.fatura,
            "endosso": cert.contrato.endosso,
            "processo_susep": cert.contrato.processo_susep,
            "codigo_pedido_porto": cert.contrato.codigo_pedido_porto,
            "estipulante": ESTIPULANTE,
            "sucursal": cert.contrato.sucursal,
            "plano": cert.contrato.plano,
            "susep_corretora": cert.contrato.susep_corretora,
        },
        "administradora": {
            "codigo": cert.administradora.codigo,
            "nome": cert.administradora.nome,
            "abreviacao": cert.administradora.abreviacao_normalizada,
            "papel": "CO-ESTIPULANTE",
        },
        "segurado": {
            "nome": cert.segurado_nome,
            "documento": cert.documento.para_dict(),
        },
        "vigencia": {
            "inicio": _data(cert.vigencia.inicio),
            "fim": _data(cert.vigencia.fim),
        },
        "local_risco": {
            "endereco": cert.local_risco.endereco,
            "unidade": cert.local_risco.unidade,
            "condominio": cert.local_risco.condominio,
            "bairro": cert.local_risco.bairro,
            "cidade": cert.local_risco.cidade,
            "uf": cert.local_risco.uf,
            "cep": cert.local_risco.cep,
        },
        "coberturas": [c.para_dict() for c in cert.coberturas],
        "premio": {
            "valor_total": para_json(cert.premio),
            "moeda": "BRL",
            "impresso_no_pdf": meta.exibe_premio,
        },
        "assistencia": {
            "codigo_mondial": cert.endosso.codigo_assist_mondial,
            "faz_tudo_lar": faz_tudo,
            "central_atendimento": CENTRAL_ATENDIMENTO,
            "central_fedcorp": CENTRAL_FEDCORP,
        },
        "_origem": {
            "banco": "FIREBIRD" if meta.modo_conexao == "firebird-local" else "API",
            "consulta": "certificado_base",
            "chave": cert.chave.para_dict(),
        },
    }


def lote_para_dict(
    certificados: Sequence[dict], lote: ChaveLote, competencia: str, nome_pdf: str
) -> dict:
    """RD-14 — envelope do modo consolidado. Os certificados vao sem `_meta` proprio."""
    return {
        "_meta": {"quantidade": len(certificados), "arquivo_pdf": nome_pdf},
        "lote": {
            "administradora": lote.administradora,
            "apolice": lote.apolice,
            "seq": lote.seq,
            "fatura": lote.fatura,
            "competencia": competencia,
        },
        "certificados": [{k: v for k, v in c.items() if k != "_meta"} for c in certificados],
    }


# ------------------------------------------------------------------ RD-15
@lru_cache(maxsize=1)
def _validador() -> Draft202012Validator:
    schema = json.loads(CAMINHO_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def erros_de_validacao(doc: dict) -> list[str]:
    return [
        f"{'/'.join(str(p) for p in e.absolute_path) or '<raiz>'}: {e.message}"
        for e in sorted(_validador().iter_errors(doc), key=lambda e: list(e.absolute_path))
    ]


def validar(doc: dict) -> None:
    """RD-15 — levanta JsonInvalido com todos os erros."""
    erros = erros_de_validacao(doc)
    if erros:
        raise JsonInvalido(erros)


def serializar(doc: dict) -> str:
    """Texto JSON deterministico (RNF-08): UTF-8 real, indentado, sem reordenar chaves."""
    return json.dumps(doc, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def gravar_json(doc: dict, caminho: Path) -> tuple[Path, bool]:
    """Valida (RD-15), resolve colisao (RN-13) e grava. Retorna (caminho_final, colidiu)."""
    validar(doc)
    texto = serializar(doc)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    destino, colidiu = resolver_colisao(caminho)
    destino.write_text(texto, encoding="utf-8")
    return destino, colidiu
