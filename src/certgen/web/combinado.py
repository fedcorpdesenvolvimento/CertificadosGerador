"""Tela + API do portal num unico processo — `certgen servidor` (ADR-08, Render).

O Render expoe uma porta por servico; o usuario decidiu (23/10/2026) que a tela com
login e o padrao e que a API do portal roda junto. As rotas `/v1/*` sao as MESMAS do
`certgen api` (mesmo router, mesmas chaves ADR-09, mesmos adaptadores — RF-11, RNF-08)
e ficam fora da sessao da tela (auth.PREFIXOS_PUBLICOS). Importar este modulo acrescenta
as rotas, o envelope de erro e o request id a `certgen.web.app.app` uma unica vez.

ADR-09: a especificacao OpenAPI da API do portal e publicada em /v1/openapi.json e
/v1/docs (so o contrato; nenhum dado), para o integrador gerar um cliente tipado. A
tela continua sem OpenAPI proprio (ADR-08).
"""

from __future__ import annotations

from fastapi import Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse

from certgen.web import api_portal
from certgen.web.app import app

if not getattr(app.state, "portal_incluido", False):

    @app.get("/v1/openapi.json", include_in_schema=False)
    def openapi_portal() -> JSONResponse:
        return JSONResponse(api_portal.app.openapi())

    @app.get("/v1/docs", include_in_schema=False)
    def docs_portal(request: Request) -> HTMLResponse:
        pagina = get_swagger_ui_html(
            openapi_url="/v1/openapi.json", title="API de Certificados FedCorp"
        )
        # o Swagger UI vem do CDN: CSP propria desta pagina (a da tela bloqueia scripts externos)
        pagina.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
            "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; img-src 'self' data: "
            "https://fastapi.tiangolo.com; connect-src 'self'; frame-ancestors 'none'"
        )
        return pagina

    api_portal.instalar_portal(app)

__all__ = ["app"]
