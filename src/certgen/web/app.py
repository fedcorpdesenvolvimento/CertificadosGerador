"""Fase 4 — API e paginas.

Menu com tres modulos (decisao do usuario, 03/09/2026 — ADR-07):
  /incendio      CERTIFICADO INCENDIO          -> este sistema (cascata 5.2, RF-01..RF-16)
  /prestamista   CERTIFICADO PRESTAMISTA/ALUG  -> sem especificacao ainda (GAP-21)
  /vida          CERTIFICADO VIDA              -> sem especificacao ainda (GAP-22)

RNF-10: servir apenas em 127.0.0.1 (ver `certgen web`).
RF-06: pasta de destino validada antes da emissao.
RF-09: a resposta traz emitidos e falhas com motivo.
Os endpoints sao `def` (sincronos): rodam no threadpool do Starlette, o que
permite usar a API sincrona do Playwright e do fdb sem bloquear o loop.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, Field

from certgen import __version__
from certgen.application.emitir_certificados import (
    OpcoesEmissao,
    emitir_lote,
    validar_pasta_destino,
)
from certgen.application.listar_cascata import Cascata, rotulo_apolice
from certgen.application.ports import RepositorioCertificados
from certgen.config.settings import Config
from certgen.domain.certificado import ChaveCertificado, ChaveLote
from certgen.domain.nomes_arquivo import NomeArquivoInvalido
from certgen.domain.produto import ProdutoIndeterminado

PASTA_WEB = Path(__file__).parent
MODULOS = [
    {"slug": "incendio", "titulo": "CERTIFICADO INCENDIO", "ativo": True,
     "descricao": "Seguro incendio / conteudo: PDF + JSON a partir do Firebird."},
    {"slug": "prestamista", "titulo": "CERTIFICADO PRESTAMISTA/ALUG", "ativo": False,
     "descricao": "Em preparacao. Sem especificacao ainda (GAP-21)."},
    {"slug": "vida", "titulo": "CERTIFICADO VIDA", "ativo": False,
     "descricao": "Em preparacao. Sem especificacao ainda (GAP-22)."},
]  # fmt: skip

app = FastAPI(title="Gerador de Certificados", version=__version__)
app.mount("/static", StaticFiles(directory=str(PASTA_WEB / "static")), name="static")


@lru_cache(maxsize=1)
def _paginas() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(PASTA_WEB / "templates")),
        autoescape=select_autoescape(["html"]),
    )


def _pagina(nome: str, **ctx) -> HTMLResponse:
    html = _paginas().get_template(nome).render(versao=__version__, modulos=MODULOS, **ctx)
    return HTMLResponse(html)


# --------------------------------------------------------------- dependencias
@lru_cache(maxsize=1)
def _config() -> Config:
    return Config.do_ambiente()


def get_repositorio() -> RepositorioCertificados:
    """Adaptador escolhido por CERTGEN_REPOSITORIO (ADR-01). Testes sobrescrevem."""
    cfg = _config()
    if cfg.repositorio == "firebird":
        from certgen.adapters.firebird.repositorio import RepositorioFirebird

        return RepositorioFirebird(susep_corretora=cfg.susep_corretora)
    raise HTTPException(501, f"adaptador '{cfg.repositorio}' ainda nao implementado (Fase 5)")


def get_config() -> Config:
    return _config()


# ------------------------------------------------------------------- paginas
@app.get("/", response_class=HTMLResponse)
def menu() -> HTMLResponse:
    return _pagina("menu.html")


@app.get("/incendio", response_class=HTMLResponse)
def pagina_incendio(cfg: Config = Depends(get_config)) -> HTMLResponse:
    return _pagina("incendio.html", pasta_padrao=str(cfg.pasta_saida), modulo=MODULOS[0])


@app.get("/prestamista", response_class=HTMLResponse)
def pagina_prestamista() -> HTMLResponse:
    return _pagina("em_construcao.html", modulo=MODULOS[1])


@app.get("/vida", response_class=HTMLResponse)
def pagina_vida() -> HTMLResponse:
    return _pagina("em_construcao.html", modulo=MODULOS[2])


# ---------------------------------------------------------------- API cascata
def _erro(exc: Exception, status: int = 400) -> JSONResponse:
    return JSONResponse({"erro": str(exc), "tipo": type(exc).__name__}, status_code=status)


@app.get("/api/incendio/administradoras")
def api_administradoras(repo: RepositorioCertificados = Depends(get_repositorio)):
    """QRY-01 — value = codigo, texto = nome (RF-03)."""
    return [
        {"codigo": a.codigo, "nome": a.nome, "abrev": a.abreviacao_normalizada,
         "possui_portal": a.possui_portal}
        for a in Cascata(repo).administradoras()
    ]  # fmt: skip


@app.get("/api/incendio/apolices")
def api_apolices(
    administradora: str = Query(""),
    inicio_vig: date | None = Query(None),
    repo: RepositorioCertificados = Depends(get_repositorio),
):
    """QRY-03 — rotulo RN-08, chave estruturada RN-17."""
    try:
        refs = Cascata(repo).apolices(administradora, inicio_vig)
    except ValueError as exc:
        return _erro(exc)
    return [{"apolice": r.apolice, "seq": r.seq, "rotulo": rotulo_apolice(r)} for r in refs]


@app.get("/api/incendio/faturas")
def api_faturas(
    administradora: str,
    apolice: str,
    seq: int,
    inicio_vig: date | None = Query(None),
    repo: RepositorioCertificados = Depends(get_repositorio),
):
    """QRY-04"""
    try:
        return Cascata(repo).faturas(administradora, apolice, seq, inicio_vig)
    except ValueError as exc:
        return _erro(exc)


@app.get("/api/incendio/segurados")
def api_segurados(
    administradora: str,
    apolice: str,
    seq: int,
    fatura: int,
    repo: RepositorioCertificados = Depends(get_repositorio),
):
    """QRY-05 — lista completa (RD-24); RF-13 derivados vem no payload."""
    lote = ChaveLote(administradora, apolice, seq, fatura)
    try:
        itens = Cascata(repo).segurados(lote)
    except ProdutoIndeterminado as exc:
        return _erro(exc, 422)
    return {
        "lote": {"administradora": administradora, "apolice": apolice, "seq": seq,
                 "fatura": fatura},  # fmt: skip
        "quantidade": len(itens),
        "produto": itens[0].produto_curto if itens else None,
        "faz_tudo_lar": itens[0].faz_tudo_lar if itens else False,
        "locacao": itens[0].locacao if itens else False,
        "segurados": [i.__dict__ for i in itens],
    }


# ---------------------------------------------------------------- API emissao
class ChaveIn(BaseModel):
    administradora: str
    apolice: str
    seq: int
    fatura: int
    certificado: str
    cpf_cnpj: str

    def dominio(self) -> ChaveCertificado:
        return ChaveCertificado(**self.model_dump())


class EmissaoIn(BaseModel):
    administradora: str
    apolice: str
    seq: int
    fatura: int
    pasta: str = Field(..., description="pasta de destino (DirectoryEdit1)")
    selecionados: list[ChaveIn] | None = Field(None, description="None = todos (RF-14)")
    imprime_premio: bool = False  # CheckBox1 — RF-10
    faz_tudo_lar: bool | None = None  # CheckBox4 — ADR-06: escolha do operador; None = RN-18
    individuais: bool = True  # CheckBox2 — RF-07
    json_unico: bool = False  # RD-26 — um JSON do lote (chave cpf|certificado), PDFs individuais
    so_xml: bool = False  # CheckBox6 'So XML de Cert.' — aqui: so JSON, sem PDF
    competencia: date | None = None  # RN-19


@app.post("/api/incendio/emitir")
def api_emitir(
    req: EmissaoIn,
    request: Request,
    repo: RepositorioCertificados = Depends(get_repositorio),
):
    """UC-01/02/03/04 — o mesmo caso de uso da CLI (RF-11)."""
    pasta = Path(req.pasta)
    try:
        validar_pasta_destino(pasta)  # RF-06
    except NomeArquivoInvalido as exc:
        return _erro(exc)

    lote = ChaveLote(req.administradora, req.apolice, req.seq, req.fatura)
    opcoes = OpcoesEmissao(
        pasta_saida=pasta,
        exibe_premio=req.imprime_premio,
        faz_tudo_lar=req.faz_tudo_lar,
        individuais=req.individuais,
        json_unico=req.json_unico,
        data_competencia=req.competencia,
        apenas=[c.dominio() for c in req.selecionados] if req.selecionados is not None else None,
        modo_conexao="firebird-local",
    )
    if req.so_xml:
        return emitir_lote(repo, lote, opcoes).para_dict()

    from certgen.render.html import DadosRender
    from certgen.render.pdf import ErroRenderizacao, RenderizadorPdf

    try:
        with RenderizadorPdf() as render:

            def renderizar(cert, meta, destino):
                dados = DadosRender(meta.gerado_em.date(), meta.exibe_premio, meta.faz_tudo_lar)
                return render.renderizar_certificado(cert, dados, destino)

            return emitir_lote(repo, lote, opcoes, renderizar_pdf=renderizar).para_dict()
    except ErroRenderizacao as exc:
        return _erro(exc, 503)


# ------------------------------------------------------------ escolha de pasta
def _dialogo_pasta(inicial: str | None) -> str | None:
    """Abre a janela nativa do Windows para escolher pasta. O servidor roda na mesma
    maquina do operador (RNF-10), entao o dialogo aparece na tela dele. Devolve None
    se cancelado."""
    import tkinter
    from tkinter import filedialog

    raiz = tkinter.Tk()
    raiz.withdraw()
    raiz.attributes("-topmost", True)
    try:
        escolhida = filedialog.askdirectory(
            title="Pasta de destino dos certificados",
            initialdir=inicial if inicial and Path(inicial).is_dir() else None,
            mustexist=True,
        )
    finally:
        raiz.destroy()
    return str(Path(escolhida)) if escolhida else None


app.state.escolher_pasta = _dialogo_pasta  # testes substituem


class PastaIn(BaseModel):
    inicial: str | None = None


@app.post("/api/escolher-pasta")
def api_escolher_pasta(req: PastaIn, request: Request):
    try:
        pasta = request.app.state.escolher_pasta(req.inicial)
    except Exception as exc:  # tkinter indisponivel, sem sessao grafica etc.
        return _erro(exc, 501)
    return {"pasta": pasta}


@app.get("/api/saude")
def saude() -> dict:
    return {"ok": True, "versao": __version__}


def _encerrar_processo() -> None:
    """Botao Sair do menu: encerra o servidor com o mesmo efeito de Ctrl+C (uvicorn desliga
    graciosamente). Roda meio segundo depois para a resposta chegar ao navegador."""
    import signal
    import threading

    threading.Timer(0.5, lambda: signal.raise_signal(signal.SIGINT)).start()


app.state.encerrar = _encerrar_processo  # testes substituem por um espiao


@app.post("/api/encerrar")
def api_encerrar(request: Request) -> dict:
    request.app.state.encerrar()
    return {"ok": True, "mensagem": "encerrando"}
