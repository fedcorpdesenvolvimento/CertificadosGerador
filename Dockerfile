# Imagem da API do portal (`certgen api`) para o Render — docs/DEPLOY-RENDER.md.
# Modelo: Dockerfile do FedHub-Backend (python slim + libfbclient2 + Playwright
# Chromium + testes no build). So a API do portal sobe aqui (RF-19, RN-30); a tela
# (`certgen web`) nao tem autenticacao e continua na rede interna (RNF-10a).

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
RUN pip install .[dev]

# Chromium do Playwright com as bibliotecas de sistema (ADR-02).
RUN python -m playwright install --with-deps chromium

# Testes unitarios e de contrato no build, como no FedHub: se falhar, o deploy
# para aqui. Integracao (Firebird) e pdf (Chromium) ficam de fora do build.
COPY tests ./tests
COPY docs/legado/referencia ./docs/legado/referencia
RUN python -m pytest -q -m "not integration and not pdf" -p no:cacheprovider

# Saida local dos PDFs/JSON (RN-34). No Render o disco e efemero: o que vale e o
# link no S3 (RF-21) e o registro no Firebird (RD-20a).
RUN mkdir -p /app/saida
ENV CERTGEN_PASTA_SAIDA=/app/saida

EXPOSE 8010

# O Render injeta PORT. `certgen api` recusa subir sem CERTGEN_API_KEY (RN-30) e
# imprime bucket e pasta de saida; `--rede` liga em 0.0.0.0 (RNF-10b) — aqui o
# TLS e dado pelo Render.
CMD ["sh", "-c", "python -m certgen.cli api --rede --porta ${PORT:-8010}"]
