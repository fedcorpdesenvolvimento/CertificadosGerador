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


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="certgen", description="Gerador de Certificados")
    p.add_argument("--version", action="version", version=f"certgen {__version__}")
    sub = p.add_subparsers(dest="comando", required=True)

    chk = sub.add_parser("check-conexao", help="Prova a conexao Firebird com SELECT 1 (Fase 0)")
    chk.set_defaults(func=_cmd_check_conexao)
    return p


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
