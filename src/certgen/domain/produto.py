"""RN-03 — Derivacao do produto a partir da apolice (e administradora).

RN-03.2: o mapa e DADO (config/produtos.toml), nao `if` em codigo.
RN-03.1: regra com administradora vence a regra so por apolice; emissao por
         essa via registra PRODUTO_POR_EXCECAO (RD-23).
RN-03.3: apolice sem regra ABORTA a emissao nomeando a apolice. Nunca herdar
         produto da selecao anterior, nunca deixar vazio (DEF-09).
GAP-14:  produtos com `emissivel = false` existem no catalogo mas nenhuma regra
         pode apontar para eles enquanto a lacuna estiver aberta.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from certgen.domain.avisos import Aviso, CodigoAviso

_ARQUIVO_PADRAO = Path(__file__).resolve().parents[1] / "config" / "produtos.toml"
_CODIGO_PRODUTO = re.compile(r"^\d{4}$")


class ProdutoIndeterminado(LookupError):
    """RN-03.3 — nenhuma regra resolve a apolice. A mensagem NOMEIA a apolice."""

    def __init__(self, apolice: str, administradora: str | None = None) -> None:
        self.apolice = apolice
        self.administradora = administradora
        adm = f", administradora {administradora}" if administradora else ""
        super().__init__(
            f"Apolice {apolice!r}{adm} nao tem produto mapeado em produtos.toml (RN-03.3). "
            "Emissao abortada."
        )


class CatalogoInvalido(ValueError):
    """produtos.toml inconsistente. Falha na carga, antes de qualquer emissao."""


@dataclass(frozen=True, slots=True)
class Produto:
    codigo: str
    descricao: str
    descricao_curta: str
    locacao: bool
    emissivel: bool = True

    def para_dict(self) -> dict[str, object]:
        return {
            "codigo": self.codigo,
            "descricao": self.descricao,
            "descricao_curta": self.descricao_curta,
            "locacao": self.locacao,
        }


@dataclass(frozen=True, slots=True)
class RegraProduto:
    apolice: str
    produto: str
    administradora: str | None = None
    motivo: str | None = None

    @property
    def especifica(self) -> bool:
        return self.administradora is not None


@dataclass(frozen=True, slots=True)
class ResolucaoProduto:
    produto: Produto
    regra: RegraProduto
    aviso: Aviso | None = None

    @property
    def avisos(self) -> list[Aviso]:
        return [self.aviso] if self.aviso else []


class CatalogoProdutos:
    """Catalogo de produtos e mapa apolice -> produto carregados do TOML."""

    def __init__(self, produtos: dict[str, Produto], regras: list[RegraProduto]) -> None:
        self._produtos = dict(produtos)
        self._regras = list(regras)
        self._validar()

    # ------------------------------------------------------------------ carga
    @classmethod
    def carregar(cls, caminho: Path | None = None) -> CatalogoProdutos:
        arq = caminho or _ARQUIVO_PADRAO
        with arq.open("rb") as fh:
            dados = tomllib.load(fh)
        return cls.de_dict(dados)

    @classmethod
    def de_dict(cls, dados: dict) -> CatalogoProdutos:
        produtos: dict[str, Produto] = {}
        for p in dados.get("produto", []):
            prod = Produto(
                codigo=str(p["codigo"]),
                descricao=p["descricao"],
                descricao_curta=p["descricao_curta"],
                locacao=bool(p.get("locacao", False)),
                emissivel=bool(p.get("emissivel", True)),
            )
            if prod.codigo in produtos:
                raise CatalogoInvalido(f"produto duplicado: {prod.codigo}")
            produtos[prod.codigo] = prod
        regras = [
            RegraProduto(
                apolice=str(r["apolice"]),
                produto=str(r["produto"]),
                administradora=(str(r["administradora"]) if r.get("administradora") else None),
                motivo=r.get("motivo"),
            )
            for r in dados.get("regra", [])
        ]
        return cls(produtos, regras)

    def _validar(self) -> None:
        if not self._produtos:
            raise CatalogoInvalido("nenhum [[produto]] definido")
        for codigo in self._produtos:
            if not _CODIGO_PRODUTO.match(codigo):
                raise CatalogoInvalido(f"codigo de produto deve ter 4 digitos: {codigo!r}")
        vistas: set[tuple[str, str | None]] = set()
        for r in self._regras:
            if r.produto not in self._produtos:
                raise CatalogoInvalido(
                    f"regra apolice={r.apolice} aponta para produto inexistente {r.produto!r}"
                )
            if not self._produtos[r.produto].emissivel:
                raise CatalogoInvalido(
                    f"regra apolice={r.apolice} aponta para produto nao emissivel "
                    f"{r.produto} (GAP-14)"
                )
            chave = (r.apolice, r.administradora)
            if chave in vistas:
                raise CatalogoInvalido(f"regra duplicada para {chave}")
            vistas.add(chave)

    # --------------------------------------------------------------- consulta
    @property
    def produtos(self) -> tuple[Produto, ...]:
        return tuple(self._produtos.values())

    @property
    def regras(self) -> tuple[RegraProduto, ...]:
        return tuple(self._regras)

    def produto(self, codigo: str) -> Produto:
        try:
            return self._produtos[codigo]
        except KeyError:
            raise CatalogoInvalido(f"produto desconhecido: {codigo!r}") from None

    def resolver(self, apolice: str, administradora: str | None = None) -> ResolucaoProduto:
        """RN-03 / RN-03.1 / RN-03.2 / RN-03.3 — a regra mais especifica vence."""
        apolice = str(apolice).strip()
        adm = str(administradora).strip() if administradora else None

        if adm is not None:
            for r in self._regras:
                if r.apolice == apolice and r.administradora == adm:
                    return ResolucaoProduto(
                        produto=self._produtos[r.produto],
                        regra=r,
                        aviso=Aviso(
                            CodigoAviso.PRODUTO_POR_EXCECAO,
                            r.motivo or f"apolice {apolice} + administradora {adm} -> {r.produto}",
                        ),
                    )
        for r in self._regras:
            if r.apolice == apolice and r.administradora is None:
                return ResolucaoProduto(produto=self._produtos[r.produto], regra=r)

        raise ProdutoIndeterminado(apolice, adm)
