"""Entidades do certificado.

RD-01 / RD-21 / RD-22: chave de identidade + cpf_cnpj para desambiguar.
RN-04:  cod_cat in {'3','4'} => locacao.
RN-18:  codigo_assist_mondial == '1003' => Faz Tudo Lar.
RN-20:  COD_0800 = certificado + ' ' + abrev; abrev ausente gera aviso.
DEF-06: final_vig nula ou 30/12/1899 (zero do TDateTime) e AUSENTE.
ADR-05: ContextoTemplate governa o template unico; matriz de 7.3.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum

from certgen.domain.avisos import Aviso, CodigoAviso
from certgen.domain.cobertura import Cobertura
from certgen.domain.documento import Documento
from certgen.domain.produto import Produto

DATA_ZERO_DELPHI = date(1899, 12, 30)
ESTIPULANTE = "FEDCORP ADMINISTRADORA DE BENEFICIOS LTDA"  # constante do layout, 7.4
CODIGO_ASSIST_FAZ_TUDO = "1003"  # RN-18
COD_CAT_LOCACAO = frozenset({"3", "4"})  # RN-04
APOLICE_MARCA_ALTERNATIVA = "15008"  # 7.3, linhas 889 e 907 do .pas


# ------------------------------------------------------------------- chaves
@dataclass(frozen=True, slots=True)
class ChaveLote:
    """Identifica uma fatura: o lote da emissao manual (RF-04)."""

    administradora: str
    apolice: str
    seq: int
    fatura: int


@dataclass(frozen=True, slots=True)
class ChaveCertificado:
    """RD-01 + RD-21: codigo_pedido_port NAO faz parte da chave."""

    administradora: str
    apolice: str
    seq: int
    fatura: int
    certificado: str
    cpf_cnpj: str  # apenas digitos (RD-22 — certificado nao e unico por fatura)

    @property
    def lote(self) -> ChaveLote:
        return ChaveLote(self.administradora, self.apolice, self.seq, self.fatura)

    def para_dict(self) -> dict[str, object]:
        return {
            "administradora": self.administradora,
            "apolice": self.apolice,
            "seq": self.seq,
            "fatura": self.fatura,
            "certificado": self.certificado,
            "cpf_cnpj": self.cpf_cnpj,
        }


# --------------------------------------------------------- objetos de valor
@dataclass(frozen=True, slots=True)
class Administradora:
    codigo: str
    nome: str
    abreviacao: str | None  # pes.abrev — RD-08
    possui_portal: bool = False  # pes.possui_portal — QRY-01, fluxo em massa (GAP-12)

    @property
    def abreviacao_normalizada(self) -> str | None:
        if self.abreviacao is None or not self.abreviacao.strip():
            return None
        return self.abreviacao.strip()

    def avisos(self) -> list[Aviso]:
        if self.abreviacao_normalizada is None:
            return [
                Aviso(
                    CodigoAviso.ABREV_ADM_AUSENTE,
                    f"administradora {self.codigo} sem abrev; COD_0800 sai incompleto (RN-20)",
                )
            ]
        return []


@dataclass(frozen=True, slots=True)
class ApoliceRef:
    """Item da lista de apolices (QRY-03). Carrega a chave estruturada (RN-17)."""

    apolice: str
    seq: int
    inicio_vig: date | None = None


@dataclass(frozen=True, slots=True)
class Vigencia:
    inicio: date | None
    fim: date | None

    @staticmethod
    def normalizar(data: date | None) -> date | None:
        """DEF-06 — nula ou zero-Delphi vira None."""
        if data is None or data == DATA_ZERO_DELPHI:
            return None
        return data

    @classmethod
    def de(cls, inicio: date | None, fim: date | None) -> Vigencia:
        return cls(cls.normalizar(inicio), cls.normalizar(fim))

    def avisos(self) -> list[Aviso]:
        if self.fim is None:
            return [Aviso(CodigoAviso.FINAL_VIG_AUSENTE, "final_vig nula ou 30/12/1899 (DEF-06)")]
        return []


@dataclass(frozen=True, slots=True)
class LocalRisco:
    endereco: str | None
    unidade: str | None
    condominio: str | None
    bairro: str | None
    cidade: str | None
    uf: str | None
    cep: str | None


@dataclass(frozen=True, slots=True)
class ContextoEndosso:
    """QRY-11 — dados do endosso que decidem o template."""

    endosso: str | None
    cod_cat: str | None
    codigo_assist_mondial: str | None

    @property
    def locacao(self) -> bool:
        """RN-04"""
        return (self.cod_cat or "").strip() in COD_CAT_LOCACAO

    @property
    def faz_tudo_lar(self) -> bool:
        """RN-18"""
        return (self.codigo_assist_mondial or "").strip() == CODIGO_ASSIST_FAZ_TUDO


@dataclass(frozen=True, slots=True)
class Contrato:
    apolice: str
    seq: int
    fatura: int
    endosso: str | None
    cod_seguradora: str | None  # RD-04 — projetado no sistema novo
    apolice_seguradora: str | None  # rotulo APOLICE no PDF
    processo_susep: str | None
    codigo_pedido_porto: int | None  # portal; nulo gera PORTAL_AUSENTE

    def avisos(self) -> list[Aviso]:
        if self.codigo_pedido_porto is None:
            return [Aviso(CodigoAviso.PORTAL_AUSENTE, "codigo_pedido_port nulo (GAP-11)")]
        return []


# ------------------------------------------------------------- template
class Marca(StrEnum):
    """Substitui Picture2/Picture7 e Memo28/Memo45 do .fr3 (7.3)."""

    PADRAO = "padrao"
    ALTERNATIVA = "alternativa"  # apenas apolice 15008


def marca_para_apolice(apolice: str) -> Marca:
    return Marca.ALTERNATIVA if str(apolice) == APOLICE_MARCA_ALTERNATIVA else Marca.PADRAO


@dataclass(frozen=True, slots=True)
class ContextoTemplate:
    """ADR-05 — objeto explicito que governa os blocos condicionais."""

    locacao: bool  # RN-04
    faz_tudo_lar: bool  # RN-18
    produto: Produto  # RN-03
    exibe_premio: bool  # RF-10
    marca: Marca

    @property
    def nome(self) -> str:
        """Nome estavel do template, gravado em _meta.template. Matriz de 7.3."""
        if self.locacao and self.faz_tudo_lar:
            return "locacao_faz_tudo"  # frxReportIncIncLocaCFT
        if self.locacao:
            return "locacao_simples"  # frxReportLocaSimples
        if self.faz_tudo_lar and self.produto.codigo == "0004":
            return "incendio_ruptura_faz_tudo"  # frxReportCntRupturaFT
        if self.faz_tudo_lar:
            return "incendio_faz_tudo_24h"  # frxReportIncW24h
        return "incendio"  # frxReportIncendio


# ------------------------------------------------------------ agregado
@dataclass(frozen=True, slots=True)
class Certificado:
    """Certificado completo: tudo que o PDF imprime e o JSON declara (RD-10)."""

    chave: ChaveCertificado
    administradora: Administradora
    contrato: Contrato
    produto: Produto
    segurado_nome: str
    documento: Documento
    vigencia: Vigencia
    local_risco: LocalRisco
    coberturas: list[Cobertura]
    premio: Decimal | None
    endosso: ContextoEndosso
    cod_0800_banco: str | None  # valor da coluna COD_0800, para conferencia (RD-08)
    avisos: list[Aviso] = field(default_factory=list)

    @property
    def numero(self) -> str:
        return self.chave.certificado

    @property
    def cod_0800(self) -> str:
        """RN-20 — recomposto na aplicacao: certificado + ' ' + abrev (se houver)."""
        abrev = self.administradora.abreviacao_normalizada
        return f"{self.numero} {abrev}" if abrev else self.numero

    def contexto_template(self, exibe_premio: bool) -> ContextoTemplate:
        return ContextoTemplate(
            locacao=self.endosso.locacao,
            faz_tudo_lar=self.endosso.faz_tudo_lar,
            produto=self.produto,
            exibe_premio=exibe_premio,
            marca=marca_para_apolice(self.chave.apolice),
        )

    def todos_avisos(self) -> list[Aviso]:
        """Avisos das partes + avisos registrados na montagem (produto por excecao, RN-02)."""
        return [
            *self.administradora.avisos(),
            *self.vigencia.avisos(),
            *self.documento.avisos(),
            *self.contrato.avisos(),
            *self.avisos,
        ]
