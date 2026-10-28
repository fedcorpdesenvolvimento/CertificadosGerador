"""Adaptador S3 da porta `PublicadorArquivos` (Fase 7 — RN-29, DEF-19, SEC-01).

Substitui o `fedcorp.jar` disparado por WinExec no legado (8.1). Diferencas:

- `boto3`, sincrono: o resultado do upload e verificado (DEF-19);
- apos o `put_object`, um `head_object` confirma existencia e tamanho antes de
  devolver o link — sem confirmacao, nenhum link e devolvido (RF-16);
- credenciais pela cadeia padrao do SDK (variaveis AWS_* no .env, perfil ou IAM),
  nunca em codigo (SEC-01, RNF-06);
- o link permanente e a URL do objeto `https://{bucket}.s3.{regiao}.amazonaws.com/{chave}`
  (formato do legado, gravado no banco e no JSON). Desde ADR-09 (28/10/2026, GAP-23
  fechado) o bucket e PRIVADO: essa URL nao abre sozinha; quem entrega o PDF pede
  `link_temporario`, uma URL assinada com prazo curto.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from certgen.application.ports import ErroPublicacao


def url_publica(bucket: str, regiao: str, chave: str) -> str:
    """RN-29 — mesmo formato de URL gravado pelo legado (linha 351 do .pas)."""
    if not bucket or not regiao or not chave or chave.startswith("/"):
        raise ErroPublicacao(f"nao e possivel montar a URL: bucket={bucket!r} chave={chave!r}")
    return f"https://{bucket}.s3.{regiao}.amazonaws.com/{chave}"


def chave_do_link(bucket: str, link: str) -> str:
    """ADR-09 — extrai a chave do objeto de um link permanente deste bucket. Aceita os
    hosts `{bucket}.s3.{regiao}.amazonaws.com`, `{bucket}.s3.amazonaws.com` e o estilo
    de caminho `s3.{regiao}.amazonaws.com/{bucket}/...` (links do legado)."""
    partes = urlsplit((link or "").strip())
    host = partes.netloc.lower()
    caminho = unquote(partes.path.lstrip("/"))
    if partes.scheme != "https" or not host or not caminho:
        raise ErroPublicacao(f"link nao e uma URL de objeto do bucket {bucket}: {link!r}")
    if host == f"{bucket.lower()}.s3.amazonaws.com" or (
        host.startswith(f"{bucket.lower()}.s3.") and host.endswith(".amazonaws.com")
    ):
        return caminho
    if host.startswith("s3.") and host.endswith(".amazonaws.com"):
        prefixo = bucket + "/"
        if caminho.startswith(prefixo) and len(caminho) > len(prefixo):
            return caminho[len(prefixo):]
    raise ErroPublicacao(f"link nao pertence ao bucket {bucket}: {link!r}")


class PublicadorS3:
    """Implementa `PublicadorArquivos` com boto3."""

    def __init__(self, bucket: str, regiao: str, cliente: Any | None = None) -> None:
        if not bucket or not regiao:
            raise ErroPublicacao("AWS_S3_BUCKET e AWS_REGION sao obrigatorios (RN-29)")
        self._bucket = bucket
        self._regiao = regiao
        self._cliente = cliente  # injetavel nos testes; criado sob demanda em producao

    def _s3(self) -> Any:
        if self._cliente is None:
            try:
                import boto3
            except ImportError as exc:  # pragma: no cover - ambiente sem boto3
                raise ErroPublicacao("Pacote boto3 nao instalado: pip install -e .") from exc
            from botocore.config import Config as ConfigBoto

            # SigV4 explicito: exigido pelas regioes novas e pelas URLs assinadas (ADR-09)
            self._cliente = boto3.client(
                "s3", region_name=self._regiao, config=ConfigBoto(signature_version="s3v4")
            )
        return self._cliente

    def publicar(self, arquivo: Path, destino: str) -> str:
        """Sobe `arquivo` em `destino`, confirma com head_object e devolve a URL publica."""
        if not arquivo.is_file():
            raise ErroPublicacao(f"arquivo a publicar nao existe: {arquivo}")
        tamanho = arquivo.stat().st_size
        if tamanho == 0:
            raise ErroPublicacao(f"arquivo vazio nao e publicado: {arquivo}")
        s3 = self._s3()
        try:
            with arquivo.open("rb") as fh:
                s3.put_object(
                    Bucket=self._bucket, Key=destino, Body=fh, ContentType="application/pdf"
                )
            cabeca = s3.head_object(Bucket=self._bucket, Key=destino)
        except Exception as exc:  # botocore lanca varias classes; unificamos (ADR-04)
            raise ErroPublicacao(f"falha ao publicar {destino} em {self._bucket}: {exc}") from exc
        remoto = int(cabeca.get("ContentLength", -1))
        if remoto != tamanho:
            raise ErroPublicacao(
                f"publicacao nao confirmada: {destino} tem {remoto} bytes no S3 e "
                f"{tamanho} bytes localmente (DEF-19)"
            )
        return url_publica(self._bucket, self._regiao, destino)

    def link_temporario(self, link: str, validade_segundos: int) -> str:
        """ADR-09 — URL assinada (SigV4) para o objeto do `link` permanente, valida por
        `validade_segundos`. Nao toca no objeto; so assina com as credenciais AWS_*."""
        if validade_segundos <= 0:
            raise ErroPublicacao("validade do link temporario deve ser positiva")
        chave = chave_do_link(self._bucket, link)
        try:
            return self._s3().generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": chave},
                ExpiresIn=validade_segundos,
            )
        except Exception as exc:  # botocore lanca varias classes; unificamos (ADR-04)
            raise ErroPublicacao(f"falha ao assinar o link de {chave}: {exc}") from exc
