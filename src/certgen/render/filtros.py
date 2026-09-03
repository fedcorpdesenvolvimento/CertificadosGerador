"""RN-14 — formatacao brasileira, apenas na apresentacao (ADR-03, RNF-12).

Nenhuma formatacao global mutavel: tudo e funcao pura, independente de locale.
Moeda `R$ 1.234.567,89`; datas `DD/MM/YYYY`; CPF `000.000.000-00`;
CNPJ `00.000.000/0000-00`; CEP `00000-000`. Ausente vira travessao (DEF-06).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from certgen.domain.documento import Documento, formatar_cnpj, formatar_cpf, somente_digitos

TRACO = "—"  # — (DEF-06: vigencia ausente e exibida assim)


def moeda(valor: Decimal | None, vazio: str = TRACO) -> str:
    """R$ 1.234.567,89"""
    if valor is None:
        return vazio
    q = Decimal(valor).quantize(Decimal("0.01"))
    negativo = q < 0
    inteiro, _, centavos = f"{abs(q):.2f}".partition(".")
    grupos = []
    while inteiro:
        grupos.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    texto = f"R$ {'.'.join(grupos)},{centavos}"
    return f"-{texto}" if negativo else texto


def data_br(valor: date | None, vazio: str = TRACO) -> str:
    """DD/MM/YYYY"""
    return vazio if valor is None else f"{valor.day:02d}/{valor.month:02d}/{valor.year:04d}"


def cep(valor: str | None, vazio: str = "") -> str:
    """00000-000. Fora de 8 digitos, devolve como veio (nao inventa mascara — DEF-08)."""
    if valor is None:
        return vazio
    d = somente_digitos(valor)
    if len(d) == 8:
        return f"{d[:5]}-{d[5:]}"
    return valor.strip() or vazio


def documento(valor: Documento | str | None, vazio: str = "") -> str:
    """CPF/CNPJ com mascara; INDEFINIDO sai como os digitos vieram."""
    if valor is None:
        return vazio
    if isinstance(valor, Documento):
        return valor.formatado or vazio
    d = somente_digitos(valor)
    if len(d) == 11:
        return formatar_cpf(d)
    if len(d) == 14:
        return formatar_cnpj(d)
    return valor.strip() or vazio


def texto(valor: object, vazio: str = "") -> str:
    """None nunca vira a string 'None' no PDF."""
    return vazio if valor is None else str(valor)


FILTROS = {
    "moeda": moeda,
    "data_br": data_br,
    "cep": cep,
    "documento": documento,
    "texto": texto,
}
