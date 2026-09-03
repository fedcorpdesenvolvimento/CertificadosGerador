"""RD-05 / ADR-03 — Dinheiro e `Decimal`; `float` e proibido.

O legado ja usa TFMTBCDField (BCD exato). Regredir para binario seria piorar.
A conversao acontece na fronteira (adaptador); aqui ficam as regras.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

Dinheiro = Decimal
CENTAVOS = Decimal("0.01")
ZERO = Decimal("0.00")


class DinheiroInvalido(ValueError):
    """Valor monetario que nao pode ser representado com exatidao."""


def para_dinheiro(valor: object) -> Decimal | None:
    """Converte um valor vindo da fronteira em Decimal com 2 casas.

    - None permanece None (RD-13: ausente != zero).
    - float e rejeitado (RD-05).
    - int, str e Decimal sao aceitos. String vazia ou so espacos vira None,
      porque e assim que o legado persiste ausencia em LINHA_BRANCA (DEF-11).
    """
    if valor is None:
        return None
    if isinstance(valor, bool):
        raise DinheiroInvalido(f"bool nao e dinheiro: {valor!r}")
    if isinstance(valor, float):
        raise DinheiroInvalido(f"float proibido para dinheiro (RD-05): {valor!r}")
    if isinstance(valor, Decimal):
        bruto = valor
    elif isinstance(valor, int):
        bruto = Decimal(valor)
    elif isinstance(valor, str):
        texto = valor.strip()
        if not texto:
            return None
        try:
            bruto = Decimal(texto.replace(",", "."))
        except InvalidOperation as exc:
            raise DinheiroInvalido(f"texto nao numerico: {valor!r}") from exc
    else:
        raise DinheiroInvalido(f"tipo nao suportado para dinheiro: {type(valor).__name__}")
    if not bruto.is_finite():
        raise DinheiroInvalido(f"valor nao finito: {valor!r}")
    return bruto.quantize(CENTAVOS, rounding=ROUND_HALF_UP)


def e_positivo(valor: Decimal | None) -> bool:
    """RN-01: cobertura conta como contratada se IS nao nula e > 0."""
    return valor is not None and valor > 0


def para_json(valor: Decimal | None) -> str | None:
    """RD-05: string decimal com 2 casas ("150000.00"), ou null."""
    return None if valor is None else format(valor.quantize(CENTAVOS), "f")
