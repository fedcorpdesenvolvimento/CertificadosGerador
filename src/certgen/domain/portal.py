"""RD-30 / RN-35a — resumo das vigencias devolvido ao portal na verificacao (UC-13, RF-20).

Revisao de 14/09/2026: a verificacao deixa de responder so `existe` e passa a devolver,
quando existe, as 3 vigencias mais recentes do documento naquela administradora, com os
dados que o portal precisa para chamar a emissao (RF-18) ja apontando fatura e
certificado. Dominio puro: sem SQL, sem HTTP (ADR-01).

Produto aqui NAO e o produto RN-03 (derivado da apolice, catalogo de 7). E o
`segurados_inc.cod_produto` (ex.: '0117'), com o nome em `produto.nom_produto` e a
descricao da fatura em `fatura_dsc_prod` — decisao do usuario em 14/09/2026.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from certgen.domain.certificado import DATA_ZERO_DELPHI


def _data_ou_none(d: date | None) -> str | None:
    """DEF-06: nula ou 30/12/1899 e ausente."""
    if d is None or d == DATA_ZERO_DELPHI:
        return None
    return d.isoformat()


@dataclass(frozen=True)
class EnderecoPortal:
    logradouro: str | None
    unidade: str | None
    bairro: str | None
    cidade: str | None
    uf: str | None
    cep: str | None
    condominio: str | None

    def para_dict(self) -> dict:
        return {
            "logradouro": self.logradouro,
            "unidade": self.unidade,
            "bairro": self.bairro,
            "cidade": self.cidade,
            "uf": self.uf,
            "cep": self.cep,
            "condominio": self.condominio,
        }


@dataclass(frozen=True)
class ProdutoPortal:
    codigo: str | None  # segurados_inc.cod_produto
    nome: str | None  # produto.nom_produto
    descricao_fatura: str | None  # fatura_dsc_prod.des_prod
    descricao_master: str | None  # fatura_dsc_prod.des_prod_master

    def para_dict(self) -> dict:
        return {
            "codigo": self.codigo,
            "nome": self.nome,
            "descricao_fatura": self.descricao_fatura,
            "descricao_master": self.descricao_master,
        }


@dataclass(frozen=True)
class VigenciaPortal:
    """Uma linha de segurados_inc vista pelo portal (RD-30)."""

    administradora: str
    cpf_cnpj: str
    nome: str | None
    endereco: EnderecoPortal
    inicio_vig: date | None
    final_vig: date | None
    apolice: str
    seq: int
    fatura: int
    certificado: str
    produto: ProdutoPortal

    def para_dict(self) -> dict:
        return {
            "nome": self.nome,
            "endereco": self.endereco.para_dict(),
            "inicio_vig": _data_ou_none(self.inicio_vig),
            "final_vig": _data_ou_none(self.final_vig),
            "apolice": self.apolice,
            "seq": self.seq,
            "fatura": self.fatura,
            "certificado": self.certificado,
            "produto": self.produto.para_dict(),
        }


def ultimas_vigencias(linhas: list[VigenciaPortal], meses: int = 3) -> list[VigenciaPortal]:
    """RN-35a — as `meses` vigencias (inicio_vig distintos) mais recentes, TODAS as linhas
    de cada uma (RD-22: mesmo CPF em mais de uma unidade). Ordem: inicio_vig desc, fatura
    desc, certificado. inicio_vig ausente (DEF-06) vai para o fim e conta como uma vigencia.
    """
    por_certificado = sorted(linhas, key=lambda v: v.certificado)
    ordenadas = sorted(  # estavel: certificado asc dentro de (inicio_vig, fatura) desc
        por_certificado, key=lambda v: (v.inicio_vig or date.min, v.fatura), reverse=True
    )
    escolhidos: list[date | None] = []
    resultado: list[VigenciaPortal] = []
    for v in ordenadas:
        if v.inicio_vig not in escolhidos:
            if len(escolhidos) == meses:
                break
            escolhidos.append(v.inicio_vig)
        resultado.append(v)
    return resultado
