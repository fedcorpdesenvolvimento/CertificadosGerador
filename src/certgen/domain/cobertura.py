"""RN-01 / RN-02 — Catalogo fechado de 11 coberturas e a cobertura derivada.

RN-01: o PDF omite coberturas com IS nula ou zero; o JSON declara todas as 11,
       sempre nesta ordem, com `contratada: false` quando nao contratada (RD-11).
GAP-16 (fechado em 03/09/2026): LINHA_BRANCA e flag S/N no banco, nao valor, e o
       negocio decidiu que nao e necessaria nesta fase. Fora do catalogo.
RN-02: COB_INCENDIO = COALESCE(inc_conteudo,0) + COALESCE(inc_predio,0), em Decimal,
       recalculada aqui e comparada com o valor do banco (DEF-05).

Os nomes sao os do exemplo canonico da secao 9.1 (sem acentos), pois e o JSON
que os consumidores contratam. A apresentacao no PDF fica em render/ (RN-14).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from certgen.domain.avisos import Aviso, CodigoAviso
from certgen.domain.dinheiro import ZERO, e_positivo, para_dinheiro, para_json


@dataclass(frozen=True, slots=True)
class DefinicaoCobertura:
    codigo: str
    nome: str
    origem: str  # coluna de origem ou "derivada"
    derivada: bool = False


# Ordem e conteudo fixados por RN-01. NAO reordenar: RD-11 exige as 12 sempre nesta sequencia.
CATALOGO: tuple[DefinicaoCobertura, ...] = (
    DefinicaoCobertura("INC_PREDIO", "Incendio - Predio", "segurados_inc.inc_predio"),
    DefinicaoCobertura("INC_CONTEUDO", "Incendio - Conteudo", "segurados_inc.inc_conteudo"),
    DefinicaoCobertura("COB_INCENDIO", "Cobertura Incendio", "derivada", derivada=True),
    DefinicaoCobertura("ALUGUEL", "Cobertura Perda de Aluguel", "segurados_inc.aluguel"),
    DefinicaoCobertura(
        "RUP_ENCANAMENTO", "Cobertura Ruptura de Encanamento", "sicb.rup_encanamento"
    ),
    DefinicaoCobertura("RC", "Cobertura RC", "sicb.rc"),
    DefinicaoCobertura("RUP_ENC_TER", "Ruptura de Encanamento - Terceiros", "sicb.rup_enc_ter"),
    DefinicaoCobertura("RESP_CIVIL", "Responsabilidade Civil", "sicb.resp_civil"),
    DefinicaoCobertura("DANOS_ELETRICOS", "Danos Eletricos", "sicb.danos_eletricos"),
    DefinicaoCobertura("QUEBRA_VIDRO", "Quebra de Vidros", "sicb.quebra_vidro"),
    DefinicaoCobertura("ACIDENTE_PESSOAL", "Acidentes Pessoais", "sicb.acidente_pessoal"),
)
CODIGOS: tuple[str, ...] = tuple(d.codigo for d in CATALOGO)

assert len(CATALOGO) == 11, "RN-01 fixa exatamente 11 coberturas"


@dataclass(frozen=True, slots=True)
class Cobertura:
    codigo: str
    nome: str
    importancia_segurada: Decimal | None
    contratada: bool
    derivada: bool = False

    @property
    def imprime_no_pdf(self) -> bool:
        """RN-01: o PDF omite IS nula ou zero."""
        return self.contratada

    def para_dict(self) -> dict[str, object]:
        d: dict[str, object] = {
            "codigo": self.codigo,
            "nome": self.nome,
            "importancia_segurada": para_json(self.importancia_segurada),
            "contratada": self.contratada,
        }
        if self.derivada:
            d["derivada"] = True
        return d


def calcular_cob_incendio(inc_conteudo: Decimal | None, inc_predio: Decimal | None) -> Decimal:
    """RN-02 — soma com COALESCE, nunca NULL (DEF-05)."""
    return (inc_conteudo or ZERO) + (inc_predio or ZERO)


def montar_coberturas(
    valores: Mapping[str, object],
    cob_incendio_banco: object = None,
) -> tuple[list[Cobertura], list[Aviso]]:
    """Constroi as 12 coberturas a partir dos valores brutos da consulta canonica.

    `valores` e indexado pelo codigo da cobertura (exceto COB_INCENDIO, que e
    derivada aqui). Chaves ausentes contam como NULL. Valores passam por
    `para_dinheiro`. Codigo fora do catalogo (ex.: LINHA_BRANCA, GAP-16) e erro.

    `cob_incendio_banco` e o valor da coluna calculada no SQL; se divergir da
    soma recalculada, gera COB_INCENDIO_DIVERGENTE (RN-02).
    """
    desconhecidas = set(valores) - set(CODIGOS)
    if desconhecidas:
        raise KeyError(f"coberturas fora do catalogo RN-01: {sorted(desconhecidas)}")

    convertidos: dict[str, Decimal | None] = {
        codigo: para_dinheiro(valores.get(codigo)) for codigo in CODIGOS if codigo != "COB_INCENDIO"
    }
    convertidos["COB_INCENDIO"] = calcular_cob_incendio(
        convertidos["INC_CONTEUDO"], convertidos["INC_PREDIO"]
    )

    avisos: list[Aviso] = []
    banco = para_dinheiro(cob_incendio_banco)
    if banco is not None and banco != convertidos["COB_INCENDIO"]:
        avisos.append(
            Aviso(
                CodigoAviso.COB_INCENDIO_DIVERGENTE,
                f"recalculada={para_json(convertidos['COB_INCENDIO'])} banco={para_json(banco)}",
            )
        )

    # RD-13: a IS e repassada como veio — ausente continua null, zero explicito
    # continua "0.00". A distincao entre "nao informado" e "informado como zero"
    # sobrevive no JSON, embora ambos sejam `contratada: false`.
    coberturas = [
        Cobertura(
            codigo=d.codigo,
            nome=d.nome,
            importancia_segurada=convertidos[d.codigo],
            contratada=e_positivo(convertidos[d.codigo]),
            derivada=d.derivada,
        )
        for d in CATALOGO
    ]
    return coberturas, avisos
