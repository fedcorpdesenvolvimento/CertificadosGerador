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


def _emitir(args: argparse.Namespace, com_pdf: bool) -> int:
    """UC-01/UC-05 — emite JSON (Fase 2) e, com `com_pdf`, tambem o PDF (Fase 3)."""
    from datetime import date
    from pathlib import Path

    from certgen.adapters.firebird.repositorio import RepositorioFirebird
    from certgen.application.emitir_certificados import OpcoesEmissao, emitir_lote
    from certgen.domain.certificado import ChaveLote

    cfg = Config.do_ambiente()
    lote = ChaveLote(args.administradora, args.apolice, args.seq, args.fatura)
    faz_tudo = {"sim": True, "nao": False, None: None}[args.faz_tudo_lar]
    opcoes = OpcoesEmissao(
        pasta_saida=Path(args.saida) if args.saida else cfg.pasta_saida,
        exibe_premio=not args.sem_premio,
        faz_tudo_lar=faz_tudo,
        json_unico=args.json_unico,
        data_competencia=date.fromisoformat(args.competencia) if args.competencia else None,
        modo_conexao="firebird-local",
    )
    repo = RepositorioFirebird(susep_corretora=cfg.susep_corretora)
    publicador = registro = None
    if com_pdf and getattr(args, "upload_aws", False):  # RF-21
        from certgen.adapters.s3.publicador import PublicadorS3

        publicador = PublicadorS3(bucket=cfg.aws_bucket, regiao=cfg.aws_region)
        registro = repo  # RD-20a: o adaptador Firebird implementa RegistroLinks

    if not com_pdf:
        relatorio = emitir_lote(repo, lote, opcoes)
    else:
        from certgen.render.html import DadosRender
        from certgen.render.pdf import ErroRenderizacao, RenderizadorPdf

        try:
            with RenderizadorPdf() as render:

                def renderizar(cert, meta, destino):
                    dados = DadosRender(meta.gerado_em.date(), meta.exibe_premio, meta.faz_tudo_lar)
                    return render.renderizar_certificado(cert, dados, destino)

                relatorio = emitir_lote(
                    repo,
                    lote,
                    opcoes,
                    renderizar_pdf=renderizar,
                    publicador=publicador,
                    registro=registro,
                )
        except ErroRenderizacao as exc:
            print("FALHA:", exc, file=sys.stderr)
            return 1
    print(relatorio.resumo())
    return 0 if not relatorio.falhas else 2


def _cmd_emitir_json(args: argparse.Namespace) -> int:
    return _emitir(args, com_pdf=False)


def _cmd_emitir(args: argparse.Namespace) -> int:
    return _emitir(args, com_pdf=True)


def _cmd_html(args: argparse.Namespace) -> int:
    """Fase 3, apoio ao layout: grava o HTML de um certificado para abrir no navegador."""
    from datetime import date
    from pathlib import Path

    from certgen.adapters.firebird.repositorio import RepositorioFirebird
    from certgen.domain.certificado import ChaveLote
    from certgen.render.html import DadosRender, renderizar_html

    cfg = Config.do_ambiente()
    repo = RepositorioFirebird(susep_corretora=cfg.susep_corretora)
    lote = ChaveLote(args.administradora, args.apolice, args.seq, args.fatura)
    certs = repo.listar_segurados(lote)
    if args.certificado:
        certs = [c for c in certs if c.chave.certificado == args.certificado]
    if not certs:
        print("FALHA: nenhum certificado encontrado", file=sys.stderr)
        return 1
    destino = Path(args.saida)
    destino.write_text(
        renderizar_html(certs[0], DadosRender(date.today(), not args.sem_premio)), encoding="utf-8"
    )
    print("OK:", destino)
    return 0


def _enderecos_rede() -> list[str]:
    import socket

    try:
        _, _, ips = socket.gethostbyname_ex(socket.gethostname())
    except OSError:
        return []
    return [ip for ip in ips if not ip.startswith("127.")]


def _cmd_web(args: argparse.Namespace) -> int:
    """Fase 4 — sobe a tela. Padrao 127.0.0.1 (RNF-10); `--rede` compartilha na LAN (RNF-10a)."""
    import threading
    import webbrowser

    import uvicorn

    host = "0.0.0.0" if args.rede else "127.0.0.1"
    url = f"http://127.0.0.1:{args.porta}/"
    print(f"Gerador de Certificados em {url}  (Sair no menu ou Ctrl+C para encerrar)")
    if args.rede:
        print("Compartilhado na rede interna (RNF-10a). A equipe acessa por:")
        for ip in _enderecos_rede() or ["<ip-desta-maquina>"]:
            print(f"   http://{ip}:{args.porta}/")
        print("Sem autenticacao: use apenas na rede interna.")
        print("Sair e Procurar... ficam disponiveis so nesta maquina.")
    if not args.sem_navegador:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run("certgen.web.app:app", host=host, port=args.porta, reload=args.reload)
    return 0


def _cmd_api(args: argparse.Namespace) -> int:
    """Fase 8 / RF-19 — API de emissao para o portal, processo separado da tela.

    RNF-10b: 127.0.0.1 por padrao; `--rede` liga em 0.0.0.0. RN-30: recusa subir sem
    CERTGEN_API_KEY (a chave nunca e impressa).
    """
    import logging

    import uvicorn

    try:
        cfg = Config.do_ambiente()
        cfg.exigir_api_key()
    except ConfiguracaoAusente as exc:
        print("FALHA:", exc, file=sys.stderr)
        return 1
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    host = "0.0.0.0" if args.rede else "127.0.0.1"
    print(f"API do portal em http://{host}:{args.porta}/v1  (docs em /docs; Ctrl+C encerra)")
    print(f"Bucket {cfg.aws_bucket} ({cfg.aws_region}); saida local em {cfg.pasta_saida}")
    if args.rede:
        print("Aceitando conexoes da rede interna (RNF-10b). Sem TLS: nao expor fora da LAN.")
        for ip in _enderecos_rede() or ["<ip-desta-maquina>"]:
            print(f"   http://{ip}:{args.porta}/v1/certificados/emitir")
    uvicorn.run("certgen.web.api_portal:app", host=host, port=args.porta, reload=args.reload)
    return 0


def _args_lote(p: argparse.ArgumentParser) -> None:
    p.add_argument("--administradora", required=True, help="codigo pessoas.pessoa, ex. 0000001192")
    p.add_argument("--apolice", required=True, help="ex. 13008")
    p.add_argument("--seq", required=True, type=int)
    p.add_argument("--fatura", required=True, type=int)
    p.add_argument("--sem-premio", action="store_true", help="RF-10: premio nao impresso")
    p.add_argument(
        "--json-unico", action="store_true",
        help="RD-26: um JSON para o lote (chave cpf|certificado); PDFs continuam individuais",
    )  # fmt: skip
    p.add_argument(
        "--faz-tudo-lar", choices=["sim", "nao"], default=None,
        help="ADR-06: forca o bloco Faz Tudo Lar; sem a opcao vale a derivacao RN-18",
    )  # fmt: skip


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="certgen", description="Gerador de Certificados")
    p.add_argument("--version", action="version", version=f"certgen {__version__}")
    sub = p.add_subparsers(dest="comando", required=True)

    chk = sub.add_parser("check-conexao", help="Prova a conexao Firebird com SELECT 1 (Fase 0)")
    chk.set_defaults(func=_cmd_check_conexao)

    for nome, func, ajuda in (
        ("emitir-json", _cmd_emitir_json, "Emite so o JSON de cada certificado de uma fatura"),
        ("emitir", _cmd_emitir, "Emite PDF + JSON de cada certificado de uma fatura"),
    ):
        em = sub.add_parser(nome, help=ajuda)
        _args_lote(em)
        em.add_argument("--saida", help="pasta raiz de saida (padrao: CERTGEN_PASTA_SAIDA)")
        em.add_argument(
            "--competencia", help="data ISO para a pasta {adm}/{MMYYYY}; padrao inicio_vig"
        )
        if nome == "emitir":
            em.add_argument(
                "--upload-aws", action="store_true",
                help="RF-21: publica cada PDF no S3 (RN-29) e grava o link no banco (RD-20a)",
            )  # fmt: skip
        em.set_defaults(func=func)

    web = sub.add_parser("web", help="Sobe a tela web em 127.0.0.1 (menu + CERTIFICADO INCENDIO)")
    web.add_argument("--porta", type=int, default=8000)
    web.add_argument("--reload", action="store_true", help="recarrega ao editar o codigo")
    web.add_argument("--sem-navegador", action="store_true", help="nao abre o navegador ao iniciar")
    web.add_argument(
        "--rede", action="store_true",
        help="RNF-10a: aceita conexoes da rede interna (0.0.0.0) para testes da equipe",
    )  # fmt: skip
    web.set_defaults(func=_cmd_web)

    api = sub.add_parser("api", help="Sobe a API de emissao para o portal (Fase 8, RF-19)")
    api.add_argument("--porta", type=int, default=8010)
    api.add_argument("--reload", action="store_true", help="recarrega ao editar o codigo")
    api.add_argument(
        "--rede", action="store_true",
        help="RNF-10b: aceita conexoes da rede interna (0.0.0.0); sem TLS, so na LAN",
    )  # fmt: skip
    api.set_defaults(func=_cmd_api)

    ht = sub.add_parser("html", help="Grava o HTML de um certificado para ajuste de layout")
    _args_lote(ht)
    ht.add_argument("--certificado", help="numero do certificado; padrao: o primeiro do lote")
    ht.add_argument("--saida", required=True, help="arquivo .html de destino")
    ht.set_defaults(func=_cmd_html)
    return p


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
