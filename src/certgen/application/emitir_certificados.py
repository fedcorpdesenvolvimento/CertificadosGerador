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
    lote_json_unico,
    lote_para_dict,
    serializar,
    validar,
)
from certgen.serialize.json_certificado import gravar_json as gravar_json_arquivo

RenderizadorPdf = Callable[[Certificado, MetaEmissao, Path], Path]


@dataclass(frozen=True)
class Emitido:
    chave: ChaveCertificado
    json_path: Path | None  # None quando o JSON e unico para o lote (RD-26)
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
    json_unico: Path | None = None  # RD-26 — um JSON para o lote, PDFs individuais

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
                    "json": str(e.json_path) if e.json_path else None,
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
            "json_unico": str(self.json_unico) if self.json_unico else None,
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
            caminho = e.pdf_path or e.json_path
            arquivo = caminho.name if caminho else e.chave.certificado
            linhas.append(f"  OK    {arquivo}{col}{av}")
        if self.json_unico:
            linhas.append(f"  JSON UNICO {self.json_unico}")
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
    faz_tudo_lar: bool | None = None  # ADR-06 — escolha do operador; None = derivacao RN-18
    individuais: bool = True  # RF-07 — False: um PDF consolidado + um JSON com o array
    json_unico: bool = False  # RD-26 — PDFs individuais, UM JSON do lote (cpf|certificado)
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
        docs: list[dict] = []
        for cert in escolhidos:
            try:
                emitido, doc = emitir_um(
                    cert, opcoes, renderizar_pdf, gravar_json=not opcoes.json_unico
                )
                relatorio.emitidos.append(emitido)
                docs.append(doc)
            except (JsonInvalido, NomeArquivoInvalido, ProdutoIndeterminado, OSError) as exc:
                relatorio.falhas.append(Falha(cert.chave, str(exc), type(exc).__name__))
        if opcoes.json_unico and docs:
            relatorio.json_unico = _gravar_json_unico(docs, escolhidos[0], opcoes)
        return relatorio

    _emitir_consolidado(escolhidos, opcoes, renderizar_pdf, relatorio)
    return relatorio


def _gravar_json_unico(docs: list[dict], primeiro: Certificado, opcoes: OpcoesEmissao) -> Path:
    """RD-26 — um JSON para o lote, indexado por `cpf_cnpj|certificado`.

    Cada item ja foi validado contra o schema (RD-15) antes do PDF ser gerado. O
    arquivo segue o nome RN-12 e vai para a mesma pasta dos PDFs (RN-19).
    """
    pasta = opcoes.pasta_saida / _pasta_destino(primeiro, opcoes)
    lote = primeiro.chave.lote
    instante = opcoes.agora()
    nome = nome_consolidado(lote.apolice, lote.seq, lote.fatura, instante, "json")
    envelope = lote_json_unico(docs, lote, instante)
    pasta.mkdir(parents=True, exist_ok=True)
    destino, _ = resolver_colisao(pasta / nome)
    destino.write_text(serializar(envelope), encoding="utf-8")
    return destino


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
                    faz_tudo_lar=opcoes.faz_tudo_lar,
                    individuais=True,
                    data_competencia=opcoes.data_competencia,
                    modo_conexao=opcoes.modo_conexao,
                    agora=lambda: instante,
                )
                emitido, doc = emitir_um(cert, sub, renderizar_pdf)
                docs.append(doc)
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


def destino_emissao(cert: Certificado, opcoes: OpcoesEmissao) -> tuple[str, Path, str]:
    """RN-19 / RD-11 — (pasta relativa, pasta absoluta, nome-base) de um certificado.

    E o unico lugar que decide onde o PDF e o JSON de um certificado ficam. `emitir_um`
    grava ali; `emitir_portal` (RN-33, RD-29) rele o JSON de la sem reemitir.
    """
    pasta_rel = _pasta_destino(cert, opcoes)
    base = nome_base_certificado(
        portal=cert.contrato.codigo_pedido_porto,
        cpf_cnpj=cert.chave.cpf_cnpj,
        produto=cert.produto.codigo,
        apolice=cert.chave.apolice,
        certificado=cert.chave.certificado,
        fatura=cert.chave.fatura,
    )
    return pasta_rel, opcoes.pasta_saida / pasta_rel, base


def emitir_um(
    cert: Certificado,
    opcoes: OpcoesEmissao,
    renderizar_pdf: RenderizadorPdf | None,
    gravar_json: bool = True,
    sobrescrever: bool = False,
) -> tuple[Emitido, dict]:
    """Emite um certificado. Devolve o registro e o documento JSON (ja validado).

    `gravar_json=False` (RD-26): valida mas nao grava o JSON individual — o lote grava
    um unico arquivo depois. A validacao continua acontecendo ANTES do PDF (RF-16).
    `sobrescrever=True` (RN-33 revista): reemissao intencional — JSON e PDF no mesmo
    caminho, sem sufixo RN-13; a API registra o aviso REEMISSAO.
    Publico desde a Fase 8: `emitir_portal` (UC-12) emite um certificado por vez com o
    MESMO passo da emissao em lote (RF-11).
    """
    pasta_rel, pasta, base = destino_emissao(cert, opcoes)
    meta = MetaEmissao(
        gerado_em=opcoes.agora(),
        nome_pdf=f"{base}.pdf",
        pasta_destino=pasta_rel,
        exibe_premio=opcoes.exibe_premio,
        modo_conexao=opcoes.modo_conexao,
        faz_tudo_lar=opcoes.faz_tudo_lar,
    )
    doc = certificado_para_dict(cert, meta)
    # RD-15 valida antes de qualquer escrita; RF-16: PDF so depois do JSON valido
    if gravar_json:
        json_path, colidiu = gravar_json_arquivo(doc, pasta / f"{base}.json", sobrescrever)
    else:
        validar(doc)
        json_path, colidiu = None, False
        pasta.mkdir(parents=True, exist_ok=True)  # o JSON individual e quem criava a pasta
    pdf_path = renderizar_pdf(cert, meta, pasta / meta.nome_pdf) if renderizar_pdf else None
    emitido = Emitido(
        chave=cert.chave,
        json_path=json_path,
        pdf_path=pdf_path,
        avisos=tuple(a["codigo"] for a in doc["_meta"]["avisos"]),
        colisao=colidiu,
    )
    return emitido, doc
