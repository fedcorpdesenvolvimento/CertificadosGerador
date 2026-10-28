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


# ------------------------------------------------------------- ADR-09: link assinado
def test_adr_09_chave_do_link_aceita_formatos_do_bucket():
    from certgen.adapters.s3.publicador import chave_do_link

    assert chave_do_link("b", "https://b.s3.us-east-2.amazonaws.com/a/x%20y.pdf") == "a/x y.pdf"
    assert chave_do_link("b", "https://b.s3.amazonaws.com/a/x.pdf") == "a/x.pdf"
    assert chave_do_link("b", "https://s3.us-east-2.amazonaws.com/b/a/x.pdf") == "a/x.pdf"
    for ruim in ("https://outro.s3.amazonaws.com/a.pdf", "http://b.s3.amazonaws.com/a.pdf",
                 "https://b.s3.amazonaws.com/", "", "nao-url"):
        with pytest.raises(ErroPublicacao):
            chave_do_link("b", ruim)


def test_adr_09_link_temporario_assina_a_chave_do_objeto():
    class S3Assina(S3Falso):
        def generate_presigned_url(self, operacao, Params, ExpiresIn):
            assert operacao == "get_object" and ExpiresIn == 900
            return f"https://assinada/{Params['Bucket']}/{Params['Key']}?X-Amz-Signature=x"

    pub = PublicadorS3("certincendioaws", "us-east-2", cliente=S3Assina())
    permanente = "https://certincendioaws.s3.us-east-2.amazonaws.com/adm/0004/x.pdf"
    link = pub.link_temporario(permanente, 900)
    assert link == "https://assinada/certincendioaws/adm/0004/x.pdf?X-Amz-Signature=x"
    with pytest.raises(ErroPublicacao):
        pub.link_temporario("https://outro.s3.amazonaws.com/x.pdf", 900)
    with pytest.raises(ErroPublicacao):
        pub.link_temporario("https://certincendioaws.s3.amazonaws.com/x.pdf", 0)
