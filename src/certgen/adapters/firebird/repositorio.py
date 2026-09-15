"""Adaptador Firebird da porta `RepositorioCertificados` (ADR-01, Fase 1).

Converte na fronteira (ADR-03): DECIMAL -> Decimal via `para_dinheiro`,
DATE -> date, zero-Delphi -> None (DEF-06). Monta o `Certificado` completo a
partir da consulta canonica (RD-24), resolvendo o produto por RN-03 e
acumulando avisos (RD-23). Falha alto (ADR-04): 0 ou >1 linhas na emissao
(RD-09) e apolice sem produto (RN-03.3) sao excecoes, nao documentos errados.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import date, datetime
from typing import Any

from certgen.adapters.firebird import conexao
from certgen.adapters.firebird.consultas import Filtros, montar
from certgen.application.ports import (
    CertificadoAmbiguo,
    CertificadoNaoEncontrado,
    LinkNaoRegistrado,
)
from certgen.domain.avisos import Aviso
from certgen.domain.certificado import (
    SUSEP_CORRETORA_PADRAO,
    Administradora,
    ApoliceRef,
    Certificado,
    ChaveCertificado,
    ChaveLote,
    ContextoEndosso,
    Contrato,
    LocalRisco,
    Vigencia,
    plano_para_tipo_categoria,
)
from certgen.domain.cobertura import montar_coberturas
from certgen.domain.dinheiro import para_dinheiro
from certgen.domain.documento import Documento
from certgen.domain.portal import EnderecoPortal, ProdutoPortal, VigenciaPortal
from certgen.domain.produto import CatalogoProdutos
from certgen.domain.seguradora import CatalogoSeguradoras

# coluna da consulta canonica -> codigo de cobertura (RN-01)
_COLUNAS_COBERTURA = {
    "inc_predio": "INC_PREDIO",
    "inc_conteudo": "INC_CONTEUDO",
    "aluguel": "ALUGUEL",
    "rup_encanamento": "RUP_ENCANAMENTO",
    "rc": "RC",
    "rup_enc_ter": "RUP_ENC_TER",
    "resp_civil": "RESP_CIVIL",
    "danos_eletricos": "DANOS_ELETRICOS",
    "quebra_vidro": "QUEBRA_VIDRO",
    "acidente_pessoal": "ACIDENTE_PESSOAL",
}


def _txt(valor: Any) -> str | None:
    """Texto descritivo: strip; vazio vira None (RD-13 distingue ausente de vazio
    apenas onde o banco distingue — aqui VARCHAR vazio e ausencia)."""
    if valor is None:
        return None
    if isinstance(valor, bytes):
        valor = valor.decode("cp1252", "replace")
    s = str(valor).strip()
    return s or None


def _inteiro(valor: Any) -> int | None:
    return None if valor is None else int(valor)


def _linhas_como_dicts(cur: Any) -> Iterator[dict[str, Any]]:
    nomes = [d[0].strip().lower() for d in cur.description]
    for row in cur.fetchall():
        yield dict(zip(nomes, row, strict=True))


class RepositorioFirebird:
    """Implementa `RepositorioCertificados` lendo o FATURA.GDB."""

    def __init__(
        self,
        catalogo: CatalogoProdutos | None = None,
        susep_corretora: str = SUSEP_CORRETORA_PADRAO,
        seguradoras: CatalogoSeguradoras | None = None,
    ) -> None:
        self._catalogo = catalogo or CatalogoProdutos.carregar()
        self._susep_corretora = susep_corretora  # RN-25
        self._seguradoras = seguradoras or CatalogoSeguradoras.carregar()  # RN-28

    # ------------------------------------------------------------ infra
    def _executar(self, nome: str, filtros: Filtros | None = None) -> list[dict[str, Any]]:
        sql, params = montar(nome, filtros)
        with conexao.conectar() as con:
            cur = con.cursor()
            cur.execute(sql, params)
            linhas = list(_linhas_como_dicts(cur))
            cur.close()
        return linhas

    # ------------------------------------------------------------ cascata
    def listar_administradoras(self) -> list[Administradora]:
        """QRY-01."""
        return [
            Administradora(
                codigo=_txt(r["pessoa"]) or "",
                nome=_txt(r["nome"]) or "",
                abreviacao=_txt(r["abrev"]),
                possui_portal=(_txt(r["possui_portal"]) or "N").upper() == "S",
            )
            for r in self._executar("administradoras")
        ]

    def listar_apolices(
        self, administradora: str, inicio_vig: date | None, data_fat: date | None = None
    ) -> list[ApoliceRef]:
        """QRY-03. RF-15: administradora vazia nao lista nada. RN-05a: data_fat opcional."""
        if not administradora:
            raise ValueError("administradora obrigatoria para listar apolices (RF-15)")
        if data_fat is not None:
            # RN-05a otimizada: parte de faturas (indice em data_fat)
            f = Filtros(parametros=[data_fat, administradora]).igual("ss.inicio_vig", inicio_vig)
            linhas = self._executar("apolices_por_data_fat", f)
        else:
            f = Filtros().igual("ss.administradora", administradora)
            f.igual("ss.inicio_vig", inicio_vig)
            linhas = self._executar("apolices", f)
        return [
            ApoliceRef(
                apolice=_txt(r["apolice"]) or "", seq=int(r["seq"]), inicio_vig=r["inicio_vig"]
            )
            for r in linhas
        ]

    def listar_faturas(
        self,
        administradora: str,
        apolice: str,
        seq: int,
        inicio_vig: date | None,
        data_fat: date | None = None,
    ) -> list[int]:
        """QRY-04. RN-05a: data_fat filtra pela data de emissao da fatura."""
        if data_fat is not None:
            # RN-05a otimizada: parte de faturas (indice em data_fat)
            f = Filtros(parametros=[data_fat, administradora, apolice, seq]).igual(
                "ss.inicio_vig", inicio_vig
            )
            linhas = self._executar("faturas_por_data_fat", f)
        else:
            f = (
                Filtros()
                .igual("ss.administradora", administradora)
                .igual("ss.apolice", apolice)
                .igual("ss.seq", seq)
                .igual("ss.inicio_vig", inicio_vig)
            )
            linhas = self._executar("faturas", f)
        return [int(r["fatura"]) for r in linhas if r["fatura"] is not None]

    # ------------------------------------------------------------ certificados
    def listar_segurados(self, lote: ChaveLote) -> list[Certificado]:
        """QRY-05 — consulta canonica + filtros de lote (RD-24)."""
        f = (
            Filtros()
            .igual("ss.administradora", lote.administradora)
            .igual("ss.apolice", lote.apolice)
            .igual("ss.seq", lote.seq)
            .igual("ss.fatura", lote.fatura)
        )
        return [self._montar(r) for r in self._executar("certificado_base", f)]

    def obter_certificado(self, chave: ChaveCertificado) -> Certificado:
        """QRY-09 + RD-21 (cpf_cnpj, sem codigo_pedido_port). RD-09: exatamente 1 linha."""
        f = (
            Filtros()
            .igual("ss.administradora", chave.administradora)
            .igual("ss.apolice", chave.apolice)
            .igual("ss.seq", chave.seq)
            .igual("ss.fatura", chave.fatura)
            .igual("ss.certificado", chave.certificado)
            .igual("ss.cpf_cnpj", chave.cpf_cnpj)
        )
        linhas = self._executar("certificado_base", f)
        if not linhas:
            raise CertificadoNaoEncontrado(chave)
        if len(linhas) > 1:
            raise CertificadoAmbiguo(chave, len(linhas))
        return self._montar(linhas[0])

    def localizar_por_portal(
        self,
        administradora: str,
        cpf_cnpj: str,
        vigencia: date,
        fatura: int | None = None,
        certificado: str | None = None,
    ) -> list[Certificado]:
        """QRY-13 / RD-27 — administradora + cpf_cnpj + inicio_vig exato (RN-31);
        fatura e certificado opcionais (RD-31), so entram quando informados (RN-07)."""
        if not (administradora and cpf_cnpj and vigencia):
            raise ValueError("administradora, cpf_cnpj e vigencia sao obrigatorios (RD-27)")
        f = (
            Filtros()
            .igual("ss.administradora", administradora)
            .igual("ss.cpf_cnpj", cpf_cnpj)
            .igual("ss.inicio_vig", vigencia)
            .igual("ss.fatura", fatura)
            .igual("ss.certificado", certificado)
        )
        return [self._montar(r) for r in self._executar("certificado_base", f)]

    def listar_vigencias_portal(self, administradora: str, cpf_cnpj: str) -> list[VigenciaPortal]:
        """QRY-14 / RD-30 — linhas nao canceladas do documento, mais recentes primeiro."""
        if not (administradora and cpf_cnpj):
            raise ValueError("administradora e cpf_cnpj sao obrigatorios (RF-20)")
        sql, _ = montar("vigencias_portal")
        with conexao.conectar() as con:
            cur = con.cursor()
            cur.execute(sql, [administradora, cpf_cnpj])
            linhas = list(_linhas_como_dicts(cur))
            cur.close()
        return [self._montar_vigencia(r) for r in linhas]

    @staticmethod
    def _montar_vigencia(r: Mapping[str, Any]) -> VigenciaPortal:
        """RD-30 — mapeia uma linha de QRY-14. final_vig zero-Delphi vira None no dict."""
        return VigenciaPortal(
            administradora=str(r["administradora"]).strip(),
            cpf_cnpj=str(r["cpf_cnpj"]).strip(),
            nome=_txt(r.get("nome")),
            endereco=EnderecoPortal(
                logradouro=_txt(r.get("endereco")),
                unidade=_txt(r.get("unidade")),
                bairro=_txt(r.get("bairro")),
                cidade=_txt(r.get("cidade")),
                uf=_txt(r.get("uf")),
                cep=_txt(r.get("cep")),
                condominio=_txt(r.get("nome_cond")),
            ),
            inicio_vig=r.get("inicio_vig"),
            final_vig=r.get("final_vig"),
            apolice=str(r["apolice"]).strip(),
            seq=_inteiro(r.get("seq")) or 0,
            fatura=int(r["fatura"]),
            certificado=str(r["certificado"]).strip(),
            produto=ProdutoPortal(
                codigo=_txt(r.get("cod_produto")),
                nome=_txt(r.get("nom_produto")),
                descricao_fatura=_txt(r.get("des_prod")),
                descricao_master=_txt(r.get("des_prod_master")),
            ),
        )

    # ------------------------------------------------------------ escrita (RD-20)
    def registrar_link(self, chave: ChaveCertificado, link: str, quando: datetime) -> None:
        """RD-20a — a unica escrita: link_certificado_aws e dt_cria_link, chave RD-01 completa.

        Exatamente 1 linha afetada; senao rollback e LinkNaoRegistrado. Implementa RegistroLinks.
        """
        sql, _ = montar("registrar_link")
        params = [
            link,
            quando,
            chave.administradora,
            chave.apolice,
            chave.seq,
            chave.fatura,
            chave.certificado,
            chave.cpf_cnpj,
        ]
        with conexao.conectar() as con:
            cur = con.cursor()
            try:
                cur.execute(sql, params)
                linhas = cur.rowcount
                if linhas != 1:
                    con.rollback()
                    raise LinkNaoRegistrado(chave, linhas)
                con.commit()
            finally:
                cur.close()

    def obter_contexto_endosso(self, fatura: int) -> ContextoEndosso:
        """QRY-11."""
        linhas = self._executar("endosso_por_fatura", Filtros(parametros=[fatura]))
        if not linhas:
            return ContextoEndosso(endosso=None, cod_cat=None, codigo_assist_mondial=None)
        r = linhas[0]
        return ContextoEndosso(
            endosso=_txt(r["endosso"]),
            cod_cat=_txt(r["cod_cat"]),
            codigo_assist_mondial=_txt(r["codigo_assist_mondial"]),
        )

    # ------------------------------------------------------------ mapeamento
    def _montar(self, r: Mapping[str, Any]) -> Certificado:
        """Linha da consulta canonica -> Certificado. Falha alto em produto indeterminado."""
        avisos: list[Aviso] = []

        administradora = Administradora(
            codigo=_txt(r["administradora"]) or "",
            nome=_txt(r["nome_adm"]) or "",
            abreviacao=_txt(r["abrev_adm"]),
        )
        # RN-03 / RN-03.1; RN-03.3 levanta ProdutoIndeterminado e aborta este certificado
        resolucao = self._catalogo.resolver(r["apolice"], administradora.codigo)
        avisos.extend(resolucao.avisos)

        documento = Documento.de(r["documento_seg"])
        coberturas, avisos_cob = montar_coberturas(
            {codigo: r.get(coluna) for coluna, codigo in _COLUNAS_COBERTURA.items()},
            cob_incendio_banco=r.get("cob_incendio"),
        )
        avisos.extend(avisos_cob)

        plano = plano_para_tipo_categoria(_txt(r.get("tipo_categoria")))  # RN-23

        certificado = str(r["certificado"])  # sem strip: participa da chave
        apolice = str(r["apolice"]).strip()
        seq, fatura = int(r["seq"]), int(r["fatura"])

        return Certificado(
            chave=ChaveCertificado(
                administradora=administradora.codigo,
                apolice=apolice,
                seq=seq,
                fatura=fatura,
                certificado=certificado,
                cpf_cnpj=documento.numero,
            ),
            administradora=administradora,
            contrato=Contrato(
                apolice=apolice,
                seq=seq,
                fatura=fatura,
                endosso=_txt(r["endosso"]),
                cod_seguradora=_txt(r["cod_seguradora"]),
                apolice_seguradora=_txt(r["apolice_seguradora"]),
                processo_susep=_txt(r["proc_susep"]),
                codigo_pedido_porto=_inteiro(r["codigo_pedido_port"]),
                sucursal=(_txt(r.get("sucursal")) or "").upper() or None,  # RN-26
                plano=plano,  # RN-23
                susep_corretora=self._susep_corretora,  # RN-25
                seguradora=self._seguradoras.resolver(_txt(r["cod_seguradora"])),  # RN-28
            ),
            produto=resolucao.produto,
            segurado_nome=_txt(r["beneficiario"]) or "",
            documento=documento,
            vigencia=Vigencia.de(r["inicio_vig"], r["final_vig"]),
            local_risco=LocalRisco(
                endereco=_txt(r["endereco"]),
                unidade=_txt(r["unidade"]),
                condominio=_txt(r["nome_cond"]),
                bairro=_txt(r["bairro"]),
                cidade=_txt(r["cidade"]),
                uf=_txt(r["uf"]),
                cep=_txt(r["cep"]),
            ),
            coberturas=coberturas,
            premio=para_dinheiro(r["premio"]),
            endosso=ContextoEndosso(
                endosso=_txt(r["endosso"]),
                cod_cat=_txt(r["cod_cat"]),
                codigo_assist_mondial=_txt(r["codigo_assist_mondial"]),
            ),
            cod_0800_banco=_txt(r["cod_0800"]),
            avisos=avisos,
            link_publicado=_txt(r.get("link_certificado_aws")),  # RD-28
        )
