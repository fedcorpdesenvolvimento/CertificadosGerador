"""CLI do gerador. Fase 0: apenas `check-conexao`.

Uso:
    python -m certgen.cli check-conexao
"""

from __future__ import annotations

import argparse
import sys

from certgen import __version__
from certgen.config.settings import Config, ConfiguracaoAusente


def _cmd_check_conexao(_: argparse.Namespace) -> int:
    from certgen.adapters.firebird.conexao import ErroConexao, verificar_conexao

    try:
        cfg = Config.do_ambiente()
        if cfg.firebird is None:
            raise ErroConexao("CERTGEN_REPOSITORIO nao e 'firebird'")
        print("OK:", verificar_conexao(cfg.firebird))
        return 0
    except (ErroConexao, ConfiguracaoAusente) as exc:
        print("FALHA:", exc, file=sys.stderr)
        return 1


def _cmd_emitir_json(args: argparse.Namespace) -> int:
    """Fase 2 — emite o JSON de todos os certificados de uma fatura (UC-01, UC-05)."""
    from datetime import date
    from pathlib import Path

    from certgen.adapters.firebird.repositorio import RepositorioFirebird
    from certgen.application.emitir_certificados import OpcoesEmissao, emitir_lote
    from certgen.domain.certificado import ChaveLote

    cfg = Config.do_ambiente()
    lote = ChaveLote(args.administradora, args.apolice, args.seq, args.fatura)
    opcoes = OpcoesEmissao(
        pasta_saida=Path(args.saida) if args.saida else cfg.pasta_saida,
        exibe_premio=not args.sem_premio,
        data_competencia=date.fromisoformat(args.competencia) if args.competencia else None,
        modo_conexao="firebird-local",
    )
    repo = RepositorioFirebird(susep_corretora=cfg.susep_corretora)
    relatorio = emitir_lote(repo, lote, opcoes)
    print(relatorio.resumo())
    return 0 if not relatorio.falhas else 2


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="certgen", description="Gerador de Certificados")
    p.add_argument("--version", action="version", version=f"certgen {__version__}")
    sub = p.add_subparsers(dest="comando", required=True)

    chk = sub.add_parser("check-conexao", help="Prova a conexao Firebird com SELECT 1 (Fase 0)")
    chk.set_defaults(func=_cmd_check_conexao)

    em = sub.add_parser("emitir-json", help="Emite o JSON de cada certificado de uma fatura")
    em.add_argument("--administradora", required=True, help="codigo pessoas.pessoa, ex. 0000001192")
    em.add_argument("--apolice", required=True, help="ex. 13008")
    em.add_argument("--seq", required=True, type=int)
    em.add_argument("--fatura", required=True, type=int)
    em.add_argument("--saida", help="pasta raiz de saida (padrao: CERTGEN_PASTA_SAIDA)")
    em.add_argument("--competencia", help="data ISO para a pasta {adm}/{MMYYYY}; padrao inicio_vig")
    em.add_argument("--sem-premio", action="store_true", help="RF-10: premio nao impresso")
    em.set_defaults(func=_cmd_emitir_json)
    return p


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
