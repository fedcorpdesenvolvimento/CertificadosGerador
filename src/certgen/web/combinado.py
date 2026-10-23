"""Tela + API do portal num unico processo — `certgen servidor` (ADR-08, Render).

O Render expoe uma porta por servico; o usuario decidiu (23/10/2026) que a tela com
login e o padrao e que a API do portal roda junto. As rotas `/v1/*` sao as MESMAS do
`certgen api` (mesmo router, mesma chave RN-30, mesmos adaptadores — RF-11, RNF-08) e
ficam fora da sessao da tela (auth.PREFIXOS_PUBLICOS). Importar este modulo acrescenta
as rotas a `certgen.web.app.app` uma unica vez.
"""

from __future__ import annotations

from certgen.web.api_portal import router as rotas_portal
from certgen.web.app import app

if not getattr(app.state, "portal_incluido", False):
    app.include_router(rotas_portal)
    app.state.portal_incluido = True

__all__ = ["app"]
