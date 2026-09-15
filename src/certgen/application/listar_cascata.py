"""Casos de uso da cascata (secao 5.2): S0 -> S1 -> S2 -> S3 -> S4.

RF-03: a administradora e escolhida pelo codigo (value do select), nunca pelo nome.
RF-15: administradora vazia bloqueia a listagem de apolices.
RN-08: rotulo da apolice e f"{apolice}.{seq}"; a chave viaja estruturada (RN-17).
RF-05: cada item da lista carrega certificado, portal, documento, nome, endereco, unidade
       e, desde 15/09/2026, a vigencia (inicio_vig e final_vig) — RF-05a.
RF-13: Produto, Faz Tudo Lar e Locacao sao derivados, exibidos somente-leitura.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from certgen.application.ports import RepositorioCertificados
from certgen.domain.certificado import (
    Administradora,
    ApoliceRef,
    Certificado,
    ChaveLote,
    Vigencia,
)


def vigencia_br(v: Vigencia) -> str:
    """RF-05a / RD-06 — "dd/mm/aaaa a dd/mm/aaaa" para tela e relatorio; fim ausente (DEF-06)
    sai como travessao, nunca 30/12/1899."""
    f = lambda d: d.strftime("%d/%m/%Y") if d else "—"  # noqa: E731
    return f"{f(v.inicio)} a {f(v.fim)}"


@dataclass(frozen=True)
class ItemSegurado:
    """Linha da lista de segurados (RF-05, RN-17)."""

    chave: dict
    certificado: str
    portal: int | None
    documento: str
    nome: str
    endereco: str
    unidade: str
    inicio_vig: str | None  # ISO (RD-06) — RF-05a
    final_vig: str | None  # ISO; None quando ausente (DEF-06)
    vigencia: str  # dd/mm/aaaa a dd/mm/aaaa, pronto para a tela
    produto: str
    produto_curto: str
    faz_tudo_lar: bool
    locacao: bool
    avisos: list[str]

    @classmethod
    def de(cls, c: Certificado) -> ItemSegurado:
        return cls(
            chave=c.chave.para_dict(),
            certificado=c.numero,
            portal=c.contrato.codigo_pedido_porto,
            documento=c.documento.formatado,
            nome=c.segurado_nome,
            endereco=c.local_risco.endereco or "",
            unidade=c.local_risco.unidade or "",
            inicio_vig=c.vigencia.inicio.isoformat() if c.vigencia.inicio else None,
            final_vig=c.vigencia.fim.isoformat() if c.vigencia.fim else None,
            vigencia=vigencia_br(c.vigencia),
            produto=c.produto.codigo,
            produto_curto=c.produto.descricao_curta,
            faz_tudo_lar=c.faz_tudo_lar_derivado,  # RN-18 / RN-18a
            locacao=c.endosso.locacao,
            avisos=[str(a.codigo) for a in c.todos_avisos()],
        )


def rotulo_apolice(ref: ApoliceRef) -> str:
    """RN-08"""
    return f"{ref.apolice}.{ref.seq}"


class Cascata:
    def __init__(self, repositorio: RepositorioCertificados) -> None:
        self._repo = repositorio

    def administradoras(self) -> list[Administradora]:
        return self._repo.listar_administradoras()

    def apolices(
        self, administradora: str, inicio_vig: date | None, data_fat: date | None = None
    ) -> list[ApoliceRef]:
        if not administradora or not administradora.strip():
            raise ValueError("Escolha a administradora antes de listar apolices (RF-15)")
        return self._repo.listar_apolices(administradora.strip(), inicio_vig, data_fat)

    def faturas(
        self,
        administradora: str,
        apolice: str,
        seq: int,
        inicio_vig: date | None,
        data_fat: date | None = None,
    ) -> list[int]:
        if not administradora or not apolice:
            raise ValueError("Administradora e apolice sao obrigatorias para listar faturas")
        return self._repo.listar_faturas(administradora, apolice, seq, inicio_vig, data_fat)

    def segurados(self, lote: ChaveLote) -> list[ItemSegurado]:
        return [ItemSegurado.de(c) for c in self._repo.listar_segurados(lote)]
