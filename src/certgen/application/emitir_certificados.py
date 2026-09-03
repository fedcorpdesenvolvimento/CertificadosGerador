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
)
from certgen.domain.produto import ProdutoIndeterminado
from certgen.serialize.json_certificado import (
    JsonInvalido,
    MetaEmissao,
    certificado_para_dict,
    gravar_json,
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

    @property
    def total(self) -> int:
        return len(self.emitidos) + len(self.falhas)

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
        return "\n".join(linhas)


@dataclass(frozen=True)
class OpcoesEmissao:
    pasta_saida: Path
    exibe_premio: bool = True  # RF-10
    data_competencia: date | None = None  # RN-19; padrao: inicio_vig do certificado
    apenas: Sequence[ChaveCertificado] | None = None  # UC-02 selecao parcial
    modo_conexao: str = "firebird-local"
    agora: Callable[[], datetime] = lambda: datetime.now().astimezone()


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
    for cert in certificados:
        if selecionadas is not None and cert.chave not in selecionadas:
            continue
        try:
            relatorio.emitidos.append(_emitir_um(cert, opcoes, renderizar_pdf))
        except (JsonInvalido, NomeArquivoInvalido, ProdutoIndeterminado, OSError) as exc:
            relatorio.falhas.append(Falha(cert.chave, str(exc), type(exc).__name__))
    return relatorio


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
