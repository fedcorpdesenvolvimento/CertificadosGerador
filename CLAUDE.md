# Gerador de Certificados

Sistema Python que emite certificados de seguro incendio/conteudo em PDF
e o JSON espelhado, lendo Firebird. Reescrita de um gerador Delphi legado
(UfrmImprimeCertInc, 1.678 linhas).

## Regra numero um

`docs/ESPECIFICACAO.md` e a fonte da verdade. Todo codigo implementa um
requisito identificado (RF-nn, RN-nn, RD-nn, QRY-nn). Cite o ID no
docstring e na mensagem de commit.

Se a especificacao nao cobre o que preciso decidir, PARE e pergunte.
Nao invente regra de negocio. Itens GAP-nn da secao 16 estao abertos e
NAO devem ser implementados por suposicao.

## Arquitetura

Hexagonal (ADR-01). Dominio sem dependencias externas. Acesso a dados so
pela porta `RepositorioCertificados` — hoje adaptador Firebird, depois
adaptador de API. Nunca chame o driver de dentro do dominio.

## Regras inviolaveis

- SQL sempre com bind parameters (RN-06). Nunca concatenar valores.
- Uma consulta canonica em queries.sql, filtros compostos em Python
  (RD-17). O legado tinha 5 copias divergentes; nao repetir isso.
- Dinheiro e `Decimal`; `float` proibido (RD-05).
- Datas sao `date`; ISO 8601 no JSON, dd/MM/yyyy no PDF (RD-06).
- Nenhuma formatacao global mutavel (RNF-12).
- Toda consulta a segurados_inc filtra status_seg <> 'C' e
  cpf_cnpj <> '' (RD-02, RD-19).
- Falhar alto em vez de emitir documento errado (ADR-04). Anomalias que
  nao impedem a emissao vao para _meta.avisos (RD-23).
- Nenhum efeito colateral antes do sucesso confirmado da etapa anterior
  (RF-16, RNF-11).
- O banco recebe UPDATE apenas em link_certificado_aws, dt_cria_link e
  id_controle_envio_portal (RNF-05).

## Conexao Firebird

Modelo copiado de `U:\--2021\04-EnvioPorto` (db.py + config.py), que segue o
FedHub-Backend: driver `fdb` (servidor e Firebird 2.5 em 192.168.0.6,
FATURA.GDB), credenciais no `.env` com os nomes `FB_HOST`, `FB_PORT`,
`FB_DATABASE`, `FB_USER`, `FB_PASSWORD`, `FB_CHARSET`, `FB_POOL_SIZE`,
pool por charset em `adapters/firebird/conexao.py`. Sempre via
`conexao.conectar()`, nunca `fdb.connect` direto. O `.env` do EnvioPorto
serve aqui sem alteracao.

## Ambiente

O projeto vive e roda direto na pasta de rede
`U:\--2021\05-Gerador Certificados` (decisao do usuario, 2026-09-03).
A `.venv` fica nessa pasta. Ative com `.\.venv\Scripts\Activate.ps1`.

## Comandos

- Instalar: `pip install -e .[dev]`
- Testes: `pytest`
- Lint: `ruff check .`
- Verificar Firebird: `python -m certgen.cli check-conexao`
- Tela web: `python -m certgen.cli web` (127.0.0.1:8000; `--reload` em desenvolvimento)
- Emissao por linha de comando: `python -m certgen.cli emitir --administradora ... --apolice ... --seq ... --fatura ...`
- CLI: `python -m certgen.cli --help`

## Menu de modulos (ADR-07)

A tela abre num menu com CERTIFICADO INCENDIO (implementado), CERTIFICADO
PRESTAMISTA/ALUG e CERTIFICADO VIDA (sem especificacao — GAP-21/22). Nao
implementar os dois ultimos por suposicao; cada um exige a mesma analise
feita para o Incendio.

## Legado

`Delphi/` e somente leitura. A analise esta na secao 13 da especificacao
(catalogo de 21 defeitos). Os PDFs de referencia estao copiados em
`docs/legado/referencia/`.
