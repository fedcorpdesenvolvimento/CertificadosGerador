"""Adaptador S3 da porta `PublicadorArquivos` (Fase 7 — RN-29, DEF-19, SEC-01).

Substitui o `fedcorp.jar` disparado por WinExec no legado (8.1). Diferencas:

- `boto3`, sincrono: o resultado do upload e verificado (DEF-19);
- apos o `put_object`, um `head_object` confirma existencia e tamanho antes de
  devolver o link — sem confirmacao, nenhum link e devolvido (RF-16);
- credenciais pela cadeia padrao do SDK (variaveis AWS_* no .env, perfil ou IAM),
  nunca em codigo (SEC-01, RNF-06);
- o link e a URL publica `https://{bucket}.s3.{regiao}.amazonaws.com/{chave}`
  (decisao do usuario em 10/09/2026; URL assinada e GAP-23).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from certgen.application.ports import ErroPublicacao


def url_publica(bucket: str, regiao: str, chave: str) -> str:
    """RN-29 — mesmo formato de URL gravado pelo legado (linha 351 do .pas)."""
    if not bucket or not regiao or not chave or chave.startswith("/"):
        raise ErroPublicacao(f"nao e possivel montar a URL: bucket={bucket!r} chave={chave!r}")
    return f"https://{bucket}.s3.{regiao}.amazonaws.com/{chave}"


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
            self._cliente = boto3.client("s3", region_name=self._regiao)
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
