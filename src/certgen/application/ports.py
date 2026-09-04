"""RD-16 — Portas. Nada de SQL nem de HTTP vaza por aqui.

ADR-01: Fase 1 implementa `RepositorioCertificados` com Firebird; Fase 5 com a API.
Trocar a origem e trocar a classe, e a configuracao escolhe.
RD-24: `listar_segurados` devolve `Certificado` completo, nao resumo — listar e
emitir usam o mesmo objeto, o que elimina DEF-03 por construcao.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Protocol

from certgen.domain.certificado import (
    Administradora,
    ApoliceRef,
    Certificado,
    ChaveCertificado,
    ChaveLote,
    ContextoEndosso,
)


class ErroRepositorio(RuntimeError):
    """Base dos erros da porta de leitura."""


class CertificadoNaoEncontrado(ErroRepositorio):
    """RD-09 — a consulta de emissao devolveu 0 linhas."""

    def __init__(self, chave: ChaveCertificado) -> None:
        self.chave = chave
        super().__init__(f"Nenhuma linha para a chave {chave.para_dict()} (RD-09)")


class CertificadoAmbiguo(ErroRepositorio):
    """RD-09 — a consulta de emissao devolveu mais de 1 linha."""

    def __init__(self, chave: ChaveCertificado, quantidade: int) -> None:
        self.chave = chave
        self.quantidade = quantidade
        super().__init__(f"{quantidade} linhas para a chave {chave.para_dict()} (RD-09)")


class RepositorioCertificados(Protocol):
    def listar_administradoras(self) -> list[Administradora]:
        """QRY-01 — apenas status <> 'C' (RD-03), ordenadas por nome."""
        ...

    def listar_apolices(
        self, administradora: str, inicio_vig: date | None, data_fat: date | None = None
    ) -> list[ApoliceRef]:
        """QRY-03 — administradora obrigatoria (RF-15). data_fat: RN-05a (Emissao:)."""
        ...

    def listar_faturas(
        self,
        administradora: str,
        apolice: str,
        seq: int,
        inicio_vig: date | None,
        data_fat: date | None = None,
    ) -> list[int]:
        """QRY-04. data_fat: RN-05a — filtra pela data de emissao da fatura (faturas.data_fat)."""
        ...

    def listar_segurados(self, lote: ChaveLote) -> list[Certificado]:
        """QRY-05 — consulta canonica filtrada pelo lote, ordem RN-10 (RD-24)."""
        ...

    def obter_certificado(self, chave: ChaveCertificado) -> Certificado:
        """QRY-09 + RD-21 — exatamente 1 linha, senao CertificadoNaoEncontrado/Ambiguo."""
        ...

    def obter_contexto_endosso(self, fatura: int) -> ContextoEndosso:
        """QRY-11 — endossos.sequencial = fatura (RN-16)."""
        ...


class PublicadorCertificados(Protocol):
    """Fase 7. Separado do repositorio porque escreve, e escrever tem outra
    politica de falha (RF-16)."""

    def publicar(self, arquivo: Path, destino: str) -> str: ...

    def registrar_link(self, chave: ChaveCertificado, link: str) -> None: ...
