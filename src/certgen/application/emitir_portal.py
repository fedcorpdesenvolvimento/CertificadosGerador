"""UC-12 / UC-13 — emissao e verificacao a pedido do portal (Fase 8, secao 11.1).

UC-12, sequencia por certificado (RF-16 aplicado, RN-33 revista, RN-34, RD-29):
  localizar (QRY-13) -> gerar JSON (validar RD-15) -> gerar PDF -> publicar (S3,
  confirmado) -> registrar_link (Firebird, exatamente 1 linha) -> regravar JSON com o
  link -> item `publicado` com o `documento` (RD-29).
RN-33 (14/09/2026): a API SEMPRE reemite, mesmo com link ja gravado (o banco tem
930 mil links do legado Delphi, sem JSON). Arquivos locais e objeto S3 sao
sobrescritos de proposito; o item leva o aviso REEMISSAO quando havia link antes.
Falha em qualquer passo interrompe AQUELE certificado, que sai como `falha`
com motivo; os demais seguem (RF-09, RN-32). Nunca se devolve link cuja
gravacao no banco nao foi confirmada, nem link sem documento.

UC-13 (RF-20, RN-35): `verificar_segurado` devolve so um booleano — o CPF/CNPJ
e segurado (nao cancelado) daquela administradora? Sem filtro de vigencia
(decisao de 14/09/2026). Nenhum dado do segurado sai.

O passo de emissao e o mesmo da tela e da CLI (`emitir_um`, RF-11); os
arquivos ficam em CERTGEN_PASTA_SAIDA com a estrutura RN-19 (RN-34).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date

from certgen.application.emitir_certificados import (
    OpcoesEmissao,
    RenderizadorPdf,
    emitir_um,
)
from certgen.application.ports import (
    ErroPublicacao,
    LinkNaoRegistrado,
    PublicadorArquivos,
    RegistroLinks,
    RepositorioCertificados,
)
from certgen.domain.certificado import Certificado, ChaveCertificado
from certgen.domain.nomes_arquivo import NomeArquivoInvalido, caminho_publicacao
from certgen.domain.produto import ProdutoIndeterminado
from certgen.serialize.json_certificado import JsonInvalido, serializar

_NAO_DIGITO = re.compile(r"\D")
_TAM_ADMINISTRADORA = 10  # pessoas.pessoa CHAR(10), secao 4.2 da especificacao
AVISO_REEMISSAO = "REEMISSAO"  # RN-33 revista: havia link gravado; foi substituido


class PedidoInvalido(ValueError):
    """RF-18 — corpo do pedido nao serve para consultar (400)."""


class NenhumCertificado(LookupError):
    """RD-27 — QRY-13 sem linhas (404)."""


def _normalizar(administradora: str, cpf_cnpj: str) -> tuple[str, str]:
    """RF-18 / RF-20 — administradora sem espacos; cpf_cnpj so digitos (a coluna guarda
    so digitos), com 11 (CPF) ou 14 (CNPJ) posicoes."""
    adm = (administradora or "").strip()
    doc = _NAO_DIGITO.sub("", cpf_cnpj or "")
    if not adm:
        raise PedidoInvalido("administradora obrigatoria")
    if len(adm) > _TAM_ADMINISTRADORA:
        # pessoas.pessoa e CHAR(10) (secao 4.2); o driver recusaria o bind com 500
        raise PedidoInvalido(
            f"administradora deve ter ate {_TAM_ADMINISTRADORA} caracteres "
            f"(codigo CHAR(10) com zeros a esquerda, ex.: 0000001192); recebido {adm!r}"
        )
    if len(doc) not in (11, 14):
        raise PedidoInvalido("cpf_cnpj deve ter 11 (CPF) ou 14 (CNPJ) digitos")
    return adm, doc


@dataclass(frozen=True)
class PedidoPortal:
    administradora: str
    cpf_cnpj: str  # apenas digitos
    vigencia: date  # = segurados_inc.inicio_vig (RN-31)

    @classmethod
    def criar(cls, administradora: str, cpf_cnpj: str, vigencia: date) -> PedidoPortal:
        """RF-18 — normaliza e valida o pedido de emissao."""
        adm, doc = _normalizar(administradora, cpf_cnpj)
        if not isinstance(vigencia, date):
            raise PedidoInvalido("vigencia deve ser uma data ISO 8601 (RD-06)")
        return cls(adm, doc, vigencia)

    def para_dict(self) -> dict:
        return {
            "administradora": self.administradora,
            "cpf_cnpj": self.cpf_cnpj,
            "vigencia": self.vigencia.isoformat(),
        }


@dataclass(frozen=True)
class PedidoVerificacao:
    """RF-20 — o portal pergunta se o documento e segurado da administradora."""

    administradora: str
    cpf_cnpj: str  # apenas digitos

    @classmethod
    def criar(cls, administradora: str, cpf_cnpj: str) -> PedidoVerificacao:
        return cls(*_normalizar(administradora, cpf_cnpj))

    def para_dict(self) -> dict:
        return {"administradora": self.administradora, "cpf_cnpj": self.cpf_cnpj}


def verificar_segurado(repositorio: RepositorioCertificados, pedido: PedidoVerificacao) -> bool:
    """UC-13 / RN-35 — True se ha linha nao cancelada (QRY-14). So o booleano; nada mais sai."""
    return bool(repositorio.existe_segurado(pedido.administradora, pedido.cpf_cnpj))


@dataclass(frozen=True)
class ItemPortal:
    chave: ChaveCertificado
    situacao: str  # publicado | falha
    link: str | None = None
    documento: dict | None = None  # RD-29: o JSON espelho (RD-10), com arquivo.link
    avisos: tuple[str, ...] = ()
    motivo: str | None = None

    def para_dict(self) -> dict:
        return {
            "chave": self.chave.para_dict(),
            "situacao": self.situacao,
            "link": self.link,
            "documento": self.documento,
            "avisos": list(self.avisos),
            "motivo": self.motivo,
        }


@dataclass
class RespostaPortal:
    pedido: PedidoPortal
    certificados: list[ItemPortal] = field(default_factory=list)

    @property
    def algum_link(self) -> bool:
        return any(i.link for i in self.certificados)

    def para_dict(self) -> dict:
        return {
            "pedido": self.pedido.para_dict(),
            "quantidade": len(self.certificados),
            "certificados": [i.para_dict() for i in self.certificados],
        }


def emitir_para_portal(
    repositorio: RepositorioCertificados,
    publicador: PublicadorArquivos,
    registro: RegistroLinks,
    pedido: PedidoPortal,
    opcoes: OpcoesEmissao,
    renderizar_pdf: RenderizadorPdf,
) -> RespostaPortal:
    """UC-12. Levanta NenhumCertificado quando QRY-13 nao encontra nada (404)."""
    try:
        certificados = repositorio.localizar_por_portal(
            pedido.administradora, pedido.cpf_cnpj, pedido.vigencia
        )
    except ProdutoIndeterminado as exc:
        # RN-03.3 — apolice sem produto: nenhum certificado desse pedido emite
        raise NenhumCertificado(str(exc)) from exc
    if not certificados:
        raise NenhumCertificado(
            f"nenhum certificado para administradora {pedido.administradora}, documento "
            f"{pedido.cpf_cnpj} e vigencia {pedido.vigencia.isoformat()} (RD-27)"
        )
    resposta = RespostaPortal(pedido=pedido)
    for cert in certificados:  # RN-32: todos
        resposta.certificados.append(
            _tratar_um(cert, publicador, registro, opcoes, renderizar_pdf)
        )
    return resposta


def _tratar_um(
    cert: Certificado,
    publicador: PublicadorArquivos,
    registro: RegistroLinks,
    opcoes: OpcoesEmissao,
    renderizar_pdf: RenderizadorPdf,
) -> ItemPortal:
    try:
        # RN-33 revista: sempre reemite; sobrescreve JSON/PDF locais (sem sufixo RN-13)
        emitido, doc = emitir_um(cert, opcoes, renderizar_pdf, sobrescrever=True)
        if emitido.pdf_path is None or emitido.json_path is None:
            raise ErroPublicacao("emissao nao produziu PDF e JSON")
        destino = caminho_publicacao(  # RN-29
            cert.chave.administradora,
            cert.produto.codigo,
            opcoes.data_competencia or cert.vigencia.inicio,
            cert.chave.fatura,
            emitido.pdf_path.name,
        )
        link = publicador.publicar(emitido.pdf_path, destino)  # confirmado (DEF-19)
        registro.registrar_link(cert.chave, link, opcoes.agora())  # 1 linha (RD-20a)
        doc["arquivo"]["link"] = link  # RD-25: JSON regravado apos upload confirmado
        texto = serializar(doc)
        emitido.json_path.write_text(texto, encoding="utf-8")
        avisos = emitido.avisos
        if cert.link_publicado:  # RD-28: havia link (novo ou do legado) — foi substituido
            avisos = (*avisos, AVISO_REEMISSAO)
        # RD-29: o documento da resposta e EXATAMENTE o que foi gravado (RNF-08)
        return ItemPortal(
            cert.chave, "publicado", link=link, documento=json.loads(texto), avisos=avisos
        )
    except (
        JsonInvalido,
        NomeArquivoInvalido,
        ProdutoIndeterminado,
        ErroPublicacao,
        LinkNaoRegistrado,
        OSError,
        json.JSONDecodeError,
    ) as exc:
        return ItemPortal(cert.chave, "falha", motivo=f"[{type(exc).__name__}] {exc}")
