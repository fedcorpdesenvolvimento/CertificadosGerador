"""UC-12 — emissao a pedido do portal (Fase 8, secao 11.1 da especificacao).

Sequencia por certificado (RF-16 aplicado, RN-33..RN-34):
  localizar (QRY-13) -> se link_publicado: devolver (RN-33)
  -> gerar JSON (validar RD-15) -> gerar PDF -> publicar (S3, confirmado)
  -> registrar_link (Firebird, exatamente 1 linha) -> regravar JSON com o link
  -> item `publicado`.
Falha em qualquer passo interrompe AQUELE certificado, que sai como `falha`
com motivo; os demais seguem (RF-09, RN-32). Nunca se devolve link cuja
gravacao no banco nao foi confirmada.

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


class PedidoInvalido(ValueError):
    """RF-18 — corpo do pedido nao serve para consultar (400)."""


class NenhumCertificado(LookupError):
    """RD-27 — QRY-13 sem linhas (404)."""


@dataclass(frozen=True)
class PedidoPortal:
    administradora: str
    cpf_cnpj: str  # apenas digitos
    vigencia: date  # = segurados_inc.inicio_vig (RN-31)

    @classmethod
    def criar(cls, administradora: str, cpf_cnpj: str, vigencia: date) -> PedidoPortal:
        """RF-18 — normaliza: cpf_cnpj vira so digitos (a coluna guarda so digitos)."""
        adm = (administradora or "").strip()
        doc = _NAO_DIGITO.sub("", cpf_cnpj or "")
        if not adm:
            raise PedidoInvalido("administradora obrigatoria")
        if len(doc) not in (11, 14):
            raise PedidoInvalido("cpf_cnpj deve ter 11 (CPF) ou 14 (CNPJ) digitos")
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
class ItemPortal:
    chave: ChaveCertificado
    situacao: str  # publicado | ja_publicado | falha
    link: str | None = None
    avisos: tuple[str, ...] = ()
    motivo: str | None = None

    def para_dict(self) -> dict:
        return {
            "chave": self.chave.para_dict(),
            "situacao": self.situacao,
            "link": self.link,
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
    if cert.link_publicado:  # RN-33
        return ItemPortal(cert.chave, "ja_publicado", link=cert.link_publicado)
    try:
        emitido, doc = emitir_um(cert, opcoes, renderizar_pdf)  # JSON valido -> PDF (RF-16)
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
        emitido.json_path.write_text(serializar(doc), encoding="utf-8")
        return ItemPortal(cert.chave, "publicado", link=link, avisos=emitido.avisos)
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
