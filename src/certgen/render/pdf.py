"""HTML -> PDF via Chromium (Playwright), ADR-02.

O PDF de referencia e uma pagina unica de 210 x 650 mm (medido no arquivo);
reproduzimos o mesmo tamanho, sem margens, com fundo impresso. O navegador e
aberto uma vez por lote e reaproveitado (RNF-03: 300 certificados em <= 120 s).
RNF-02: texto selecionavel — Chromium gera PDF com texto real, nao imagem.
"""

from __future__ import annotations

from pathlib import Path
from types import TracebackType

from certgen.domain.certificado import Certificado
from certgen.render.html import DadosRender, renderizar_html

LARGURA_MM = 210
ALTURA_MM = 650


class ErroRenderizacao(RuntimeError):
    """Chromium indisponivel ou falha ao gerar o PDF."""


class RenderizadorPdf:
    """Uso: `with RenderizadorPdf() as r: r.pdf(html, destino)`."""

    def __init__(self) -> None:
        self._pw = None
        self._browser = None

    def __enter__(self) -> RenderizadorPdf:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise ErroRenderizacao("playwright nao instalado: pip install -e .") from exc
        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.launch()
        except Exception as exc:
            self._pw.stop()
            raise ErroRenderizacao(
                f"Chromium indisponivel ({exc.__class__.__name__}). "
                "Rode: python -m playwright install chromium"
            ) from exc
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._browser is not None:
            self._browser.close()
        if self._pw is not None:
            self._pw.stop()
        self._browser = self._pw = None

    def pdf(self, html: str, destino: Path) -> Path:
        if self._browser is None:
            raise ErroRenderizacao("use dentro de `with RenderizadorPdf()`")
        destino.parent.mkdir(parents=True, exist_ok=True)
        page = self._browser.new_page()
        try:
            page.set_content(html, wait_until="load")
            page.emulate_media(media="print")
            page.pdf(
                path=str(destino),
                width=f"{LARGURA_MM}mm",
                height=f"{ALTURA_MM}mm",
                print_background=True,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
                prefer_css_page_size=True,
            )
        finally:
            page.close()
        return destino

    def renderizar_certificado(self, cert: Certificado, dados: DadosRender, destino: Path) -> Path:
        return self.pdf(renderizar_html(cert, dados), destino)


def html_para_pdf(html: str, destino: Path) -> Path:
    """Conveniencia para um unico documento (abre e fecha o navegador)."""
    with RenderizadorPdf() as r:
        return r.pdf(html, destino)
