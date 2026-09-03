"""Fixtures compartilhadas.

Os tres arquivos de referencia da secao 7.2 da especificacao, decompostos.
O terceiro campo vazio nos dois `15008` e o DEF-09 fotografado.
"""

from __future__ import annotations

from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
PASTA_REFERENCIA = RAIZ / "docs" / "legado" / "referencia"

# (arquivo legado, portal, cpf_cnpj, produto legado, apolice, certificado real, fatura)
REFERENCIA = [
    (
        "0_33016330725_0004_13008_380819.pdf",
        0, "33016330725", "0004", "13008", "CF1DI/AP.602", 380819,
    ),
    (
        "0_05554363733__15008_381066.pdf",
        0, "05554363733", "", "15008", "3082/01/AP 1302", 381066,
    ),
    (
        "0_14529138704__15008_381066.pdf",
        0, "14529138704", "", "15008", "3082/01/AP 1101", 381066,
    ),
]  # fmt: skip


@pytest.fixture(scope="session")
def arquivos_referencia() -> list[tuple]:
    return REFERENCIA


@pytest.fixture(scope="session")
def pasta_referencia() -> Path:
    return PASTA_REFERENCIA
