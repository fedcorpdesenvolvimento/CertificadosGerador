# Imagem da tela + API do portal (`certgen servidor`) para o Render — docs/DEPLOY-RENDER.md.
# Modelo: Dockerfile do FedHub-Backend (python slim + libfbclient2 + Playwright
# Chromium + testes no build). Desde ADR-08 (23/10/2026) a tela tem login e sobe junto
# com as rotas /v1 do portal (RN-30) no mesmo processo.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# libfbclient2: biblioteca cliente que o driver `fdb` carrega (o servidor e
# Firebird 2.5; o cliente 3.x negocia o protocolo, como no FedHub).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libfbclient2 \
    && rm -rf /var/lib/apt/lists/*

# Dependencias primeiro, para a camada ser reaproveitada entre builds.
COPY pyproject.toml README.md ./
COPY src ./src
# Editavel (-e): o codigo resolve a raiz do projeto a partir do proprio arquivo
# (settings.RAIZ_PROJETO -> docs/schema, RD-15); instalado em site-packages a
# raiz apontaria para fora de /app.
RUN pip install -e .[dev]

# Chromium do Playwright com as bibliotecas de sistema (ADR-02).
RUN python -m playwright install --with-deps chromium

# Testes unitarios e de contrato no build, como no FedHub: se falhar, o deploy
# para aqui. Integracao (Firebird) e pdf (Chromium) ficam de fora do build.
COPY tests ./tests
COPY docs/schema ./docs/schema
COPY docs/legado/referencia ./docs/legado/referencia
RUN python -m pytest -q -m "not integration and not pdf" -p no:cacheprovider

# Saida local dos PDFs/JSON (RN-34). No Render o disco e efemero: o que vale e o
# link no S3 (RF-21) e o registro no Firebird (RD-20a).
RUN mkdir -p /app/saida
ENV CERTGEN_PASTA_SAIDA=/app/saida

EXPOSE 8010

# O Render injeta PORT. `certgen servidor` (ADR-08) sobe a tela com login e as rotas /v1
# do portal no mesmo processo; recusa subir sem CERTGEN_API_KEY (RN-30). `--proxy` confia
# nos X-Forwarded-* do Render (cookie Secure, IP real); o TLS e dado pelo Render.
CMD ["sh", "-c", "python -m certgen.cli servidor --rede --proxy --porta ${PORT:-8010}"]
