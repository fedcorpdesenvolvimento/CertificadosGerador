"""RF-07 / RF-09 / RF-11 / RF-16 — caso de uso de emissao.

Fase 2: emite o JSON de cada certificado do lote. A renderizacao do PDF entra
na Fase 3 pelo mesmo caso de uso (parametro `renderizar_pdf`), sem duplicar o
fluxo (RF-11: um unico caso de uso parametrizado).

RF-09: falha em um certificado nao interrompe o lote; entra no relatorio.
ADR-04: produto indeterminado, RD-09 e JSON invalido abortam aquele certificado.
RF-16/RNF-11: nada e gravado antes do passo anterior ter sucesso — o JSON so
e escrito depois de validar.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from certgen.application.ports import RepositorioCertificados
from certgen.domain.certificado import Certificado, ChaveCertificado, ChaveLote
from certgen.domain.nomes_arquivo import (
    NomeArquivoInvalido,
    competencia,
    nome_base_certificado,
    nome_consolidado,
    resolver_colisao,
)
from certgen.domain.produto import ProdutoIndeterminado
from certgen.serialize.json_certificado import (
    JsonInvalido,
    MetaEmissao,
    certificado_para_dict,
    gravar_json,
    lote_para_dict,
    serializar,
)

RenderizadorPdf = Callable[[Certificado, MetaEmissao, Path], Path]


@dataclass(frozen=True)
class Emitido:
    chave: ChaveCertificado
    json_path: Path
    pdf_path: Path | None
    avisos: tuple[str, ...]
    colisao: bool = False


@dataclass(frozen=True)
class Falha:
    chave: ChaveCertificado | None
    motivo: str
    tipo: str  # nome da excecao


@dataclass
class Relatorio:
    lote: ChaveLote
    pasta: Path
    emitidos: list[Emitido] = field(default_factory=list)
    falhas: list[Falha] = field(default_factory=list)
    consolidado_pdf: Path | None = None  # RF-07 modo consolidado (RN-12)
    consolidado_json: Path | None = None

    @property
    def total(self) -> int:
        return len(self.emitidos) + len(self.falhas)

    def para_dict(self) -> dict:
        return {
            "lote": {
                "administradora": self.lote.administradora,
                "apolice": self.lote.apolice,
                "seq": self.lote.seq,
                "fatura": self.lote.fatura,
            },
            "pasta": str(self.pasta),
            "emitidos": [
                {
                    "chave": e.chave.para_dict(),
                    "json": str(e.json_path),
                    "pdf": str(e.pdf_path) if e.pdf_path else None,
                    "avisos": list(e.avisos),
                    "colisao": e.colisao,
                }
                for e in self.emitidos
            ],
            "falhas": [
                {
                    "chave": f.chave.para_dict() if f.chave else None,
                    "tipo": f.tipo,
                    "motivo": f.motivo,
                }
                for f in self.falhas
            ],
            "consolidado_pdf": str(self.consolidado_pdf) if self.consolidado_pdf else None,
            "consolidado_json": str(self.consolidado_json) if self.consolidado_json else None,
        }

    def resumo(self) -> str:
        linhas = [
            f"Lote {self.lote.administradora}/{self.lote.apolice}.{self.lote.seq} "
            f"fatura {self.lote.fatura}: {len(self.emitidos)} emitidos, "
            f"{len(self.falhas)} falhas, pasta {self.pasta}"
        ]
        for e in self.emitidos:
            av = f"  avisos: {', '.join(e.avisos)}" if e.avisos else ""
            col = "  (colisao: sufixo aplicado)" if e.colisao else ""
            linhas.append(f"  OK    {e.json_path.name}{col}{av}")
        for f in self.falhas:
            cert = f.chave.certificado if f.chave else "?"
            linhas.append(f"  FALHA {cert}: [{f.tipo}] {f.motivo}")
        if self.consolidado_pdf or self.consolidado_json:
            pdf, js = self.consolidado_pdf or "", self.consolidado_json or ""
            linhas.append(f"  CONSOLIDADO {pdf} {js}")
        return "\n".join(linhas)


@dataclass(frozen=True)
class OpcoesEmissao:
    pasta_saida: Path
    exibe_premio: bool = True  # RF-10
    individuais: bool = True  # RF-07 — False: um PDF consolidado + um JSON com o array
    data_competencia: date | None = None  # RN-19; padrao: inicio_vig do certificado
    apenas: Sequence[ChaveCertificado] | None = None  # UC-02 selecao parcial
    modo_conexao: str = "firebird-local"
    agora: Callable[[], datetime] = lambda: datetime.now().astimezone()


def validar_pasta_destino(pasta: Path) -> None:
    """RF-06 — pasta existente e gravavel ANTES de iniciar a emissao."""
    if not pasta.exists():
        raise NomeArquivoInvalido(f"pasta de destino nao existe: {pasta}")
    if not pasta.is_dir():
        raise NomeArquivoInvalido(f"destino nao e uma pasta: {pasta}")
    sonda = pasta / f".certgen_sonda_{os.getpid()}"
    try:
        sonda.write_text("", encoding="utf-8")
        sonda.unlink()
    except OSError as exc:
        raise NomeArquivoInvalido(
            f"pasta de destino sem permissao de escrita: {pasta} ({exc})"
        ) from exc


def _pasta_destino(cert: Certificado, opcoes: OpcoesEmissao) -> str:
    """RN-19 — {administradora}/{competencia}. Competencia da opcao ou do inicio_vig."""
    data = opcoes.data_competencia or cert.vigencia.inicio
    if data is None:
        raise NomeArquivoInvalido(
            "sem data para a competencia: inicio_vig ausente e nenhuma data informada (RN-19)"
        )
    return f"{cert.chave.administradora}/{competencia(data)}"


def emitir_lote(
    repositorio: RepositorioCertificados,
    lote: ChaveLote,
    opcoes: OpcoesEmissao,
    renderizar_pdf: RenderizadorPdf | None = None,
) -> Relatorio:
    """UC-01/UC-02/UC-05 — emite JSON (e PDF, quando houver renderizador) de um lote."""
    relatorio = Relatorio(lote=lote, pasta=opcoes.pasta_saida)
    try:
        certificados = repositorio.listar_segurados(lote)
    except ProdutoIndeterminado as exc:
        # RN-03.3 — a apolice inteira nao tem produto; nenhum certificado do lote emite
        relatorio.falhas.append(Falha(None, str(exc), type(exc).__name__))
        return relatorio

    selecionadas = set(opcoes.apenas) if opcoes.apenas is not None else None
    escolhidos = [
        c for c in certificados if selecionadas is None or c.chave in selecionadas
    ]

    if opcoes.individuais:
        for cert in escolhidos:
            try:
                relatorio.emitidos.append(_emitir_um(cert, opcoes, renderizar_pdf))
            except (JsonInvalido, NomeArquivoInvalido, ProdutoIndeterminado, OSError) as exc:
                relatorio.falhas.append(Falha(cert.chave, str(exc), type(exc).__name__))
        return relatorio

    _emitir_consolidado(escolhidos, opcoes, renderizar_pdf, relatorio)
    return relatorio


def _emitir_consolidado(
    certificados: list[Certificado],
    opcoes: OpcoesEmissao,
    renderizar_pdf: RenderizadorPdf | None,
    relatorio: Relatorio,
) -> None:
    """RF-07 (Individuais desmarcado) — um PDF consolidado gravado + um JSON com o array.

    RN-12 nomeia; RF-08 mantem a ordem da consulta (RN-10); DEF-15 corrigido: grava, nao
    apenas pre-visualiza. Os individuais sao gerados numa pasta temporaria e descartados.
    """
    if not certificados:
        return
    primeiro = certificados[0]
    pasta_rel = _pasta_destino(primeiro, opcoes)
    pasta = opcoes.pasta_saida / pasta_rel
    instante = opcoes.agora()
    lote = primeiro.chave.lote
    base = nome_consolidado(lote.apolice, lote.seq, lote.fatura, instante, "pdf")[:-4]
    temporaria = pasta / f".{base}.tmp"

    docs: list[dict] = []
    pdfs: list[Path] = []
    try:
        for cert in certificados:
            try:
                sub = OpcoesEmissao(
                    pasta_saida=temporaria,
                    exibe_premio=opcoes.exibe_premio,
                    individuais=True,
                    data_competencia=opcoes.data_competencia,
                    modo_conexao=opcoes.modo_conexao,
                    agora=lambda: instante,
                )
                emitido = _emitir_um(cert, sub, renderizar_pdf)
                docs.append(json.loads(emitido.json_path.read_text(encoding="utf-8")))
                if emitido.pdf_path:
                    pdfs.append(emitido.pdf_path)
                relatorio.emitidos.append(emitido)
            except (JsonInvalido, NomeArquivoInvalido, ProdutoIndeterminado, OSError) as exc:
                relatorio.falhas.append(Falha(cert.chave, str(exc), type(exc).__name__))

        if not docs:
            return
        pasta.mkdir(parents=True, exist_ok=True)
        comp = competencia(opcoes.data_competencia or primeiro.vigencia.inicio)
        envelope = lote_para_dict(docs, lote, comp, f"{base}.pdf")
        destino_json, _ = resolver_colisao(pasta / f"{base}.json")
        destino_json.write_text(serializar(envelope), encoding="utf-8")
        relatorio.consolidado_json = destino_json
        if pdfs:
            from pypdf import PdfWriter

            destino_pdf, _ = resolver_colisao(pasta / f"{base}.pdf")
            writer = PdfWriter()
            for p in pdfs:
                writer.append(str(p))
            with destino_pdf.open("wb") as fh:
                writer.write(fh)
            relatorio.consolidado_pdf = destino_pdf
    finally:
        shutil.rmtree(temporaria, ignore_errors=True)


def _emitir_um(
    cert: Certificado, opcoes: OpcoesEmissao, renderizar_pdf: RenderizadorPdf | None
) -> Emitido:
    pasta_rel = _pasta_destino(cert, opcoes)
    pasta = opcoes.pasta_saida / pasta_rel
    base = nome_base_certificado(
        portal=cert.contrato.codigo_pedido_porto,
        cpf_cnpj=cert.chave.cpf_cnpj,
        produto=cert.produto.codigo,
        apolice=cert.chave.apolice,
        certificado=cert.chave.certificado,
        fatura=cert.chave.fatura,
    )
    meta = MetaEmissao(
        gerado_em=opcoes.agora(),
        nome_pdf=f"{base}.pdf",
        pasta_destino=pasta_rel,
        exibe_premio=opcoes.exibe_premio,
        modo_conexao=opcoes.modo_conexao,
    )
    doc = certificado_para_dict(cert, meta)
    # RD-15 valida antes de qualquer escrita; RF-16: PDF so depois do JSON valido
    json_path, colidiu = gravar_json(doc, pasta / f"{base}.json")
    pdf_path = renderizar_pdf(cert, meta, pasta / meta.nome_pdf) if renderizar_pdf else None
    return Emitido(
        chave=cert.chave,
        json_path=json_path,
        pdf_path=pdf_path,
        avisos=tuple(str(a.codigo) for a in cert.todos_avisos()),
        colisao=colidiu,
    )
