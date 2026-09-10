"""RN-29 / DEF-19 — adaptador S3 com cliente falso (sem rede)."""

from __future__ import annotations

import pytest

from certgen.adapters.s3.publicador import PublicadorS3, url_publica
from certgen.application.ports import ErroPublicacao


class S3Falso:
    def __init__(self, tamanho_remoto=None, erro=None):
        self.objetos = {}
        self.tamanho_remoto = tamanho_remoto
        self.erro = erro

    def put_object(self, Bucket, Key, Body, ContentType):
        if self.erro:
            raise self.erro
        assert ContentType == "application/pdf"
        self.objetos[(Bucket, Key)] = Body.read()

    def head_object(self, Bucket, Key):
        n = len(self.objetos[(Bucket, Key)])
        return {"ContentLength": self.tamanho_remoto if self.tamanho_remoto is not None else n}


def test_rn_29_url_publica():
    assert (
        url_publica("certincendioaws", "us-east-2", "a/b/c.pdf")
        == "https://certincendioaws.s3.us-east-2.amazonaws.com/a/b/c.pdf"
    )


def test_publica_confirma_e_devolve_link(tmp_path):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF conteudo")
    s3 = S3Falso()
    link = PublicadorS3("certincendioaws", "us-east-2", cliente=s3).publicar(pdf, "adm/0004/x.pdf")
    assert link == "https://certincendioaws.s3.us-east-2.amazonaws.com/adm/0004/x.pdf"
    assert s3.objetos[("certincendioaws", "adm/0004/x.pdf")] == b"%PDF conteudo"


def test_def_19_tamanho_divergente_nao_devolve_link(tmp_path):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF conteudo")
    with pytest.raises(ErroPublicacao, match="DEF-19"):
        PublicadorS3("b", "r", cliente=S3Falso(tamanho_remoto=3)).publicar(pdf, "k.pdf")


def test_erro_do_sdk_vira_erro_publicacao(tmp_path):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF")
    with pytest.raises(ErroPublicacao):
        PublicadorS3("b", "r", cliente=S3Falso(erro=RuntimeError("rede"))).publicar(pdf, "k")


def test_arquivo_ausente_ou_vazio(tmp_path):
    with pytest.raises(ErroPublicacao):
        PublicadorS3("b", "r", cliente=S3Falso()).publicar(tmp_path / "nao.pdf", "k")
    vazio = tmp_path / "v.pdf"
    vazio.write_bytes(b"")
    with pytest.raises(ErroPublicacao):
        PublicadorS3("b", "r", cliente=S3Falso()).publicar(vazio, "k")
