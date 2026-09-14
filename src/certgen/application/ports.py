"""RD-16 — Portas. Nada de SQL nem de HTTP vaza por aqui.

ADR-01: Fase 1 implementa `RepositorioCertificados` com Firebird; Fase 5 com a API.
Trocar a origem e trocar a classe, e a configuracao escolhe.
RD-24: `listar_segurados` devolve `Certificado` completo, nao resumo — listar e
emitir usam o mesmo objeto, o que elimina DEF-03 por construcao.
"""

from __future__ import annotations

from datetime import date, datetime
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

    def localizar_por_portal(
        self, administradora: str, cpf_cnpj: str, vigencia: date
    ) -> list[Certificado]:
        """QRY-13 / RD-27 — consulta canonica filtrada por administradora, cpf_cnpj e
        inicio_vig exato (RN-31). 0, 1 ou N linhas; quem chama decide (RN-32)."""
        ...

    def existe_segurado(self, administradora: str, cpf_cnpj: str) -> bool:
        """QRY-14 / RN-35 (UC-13) — True se houver ao menos uma linha nao cancelada da
        administradora com esse documento, sem olhar vigencia (decisao de 14/09/2026).
        Nenhum dado do segurado e devolvido (RF-20)."""
        ...


class ErroPublicacao(RuntimeError):
    """Falha ao publicar o arquivo ou ao confirmar a publicacao (DEF-19)."""


class LinkNaoRegistrado(RuntimeError):
    """RD-20a — o UPDATE nao afetou exatamente 1 linha; nada foi gravado."""

    def __init__(self, chave: ChaveCertificado, linhas: int) -> None:
        self.chave = chave
        self.linhas = linhas
        super().__init__(
            f"registrar_link afetaria {linhas} linhas para {chave.para_dict()}; rollback (RD-20a)"
        )


class PublicadorArquivos(Protocol):
    """Fase 7. Separado do repositorio porque escreve, e escrever tem outra
    politica de falha (RF-16). Adaptador: S3 via boto3 (RN-29)."""

    def publicar(self, arquivo: Path, destino: str) -> str:
        """Sobe `arquivo` em `destino` (caminho relativo no bucket), confirma e devolve o
        link publico. Levanta ErroPublicacao se nao conseguir confirmar (DEF-19)."""
        ...


class RegistroLinks(Protocol):
    """Fase 7. A unica escrita no banco (RD-20, RD-20a, RNF-05). Adaptador: Firebird."""

    def registrar_link(self, chave: ChaveCertificado, link: str, quando: datetime) -> None:
        """UPDATE de link_certificado_aws e dt_cria_link pela chave RD-01; exatamente 1 linha,
        senao LinkNaoRegistrado."""
        ...
