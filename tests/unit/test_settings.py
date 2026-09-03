"""Fase 0 — configuracao no modelo EnvioPorto/FedHub (RNF-06, ADR-01, RN-22)."""

import pytest

from certgen.config.settings import (
    Config,
    ConfigFirebird,
    ConfiguracaoAusente,
    carregar_dotenv,
    env_obrigatoria,
)

FB_COMPLETO = {
    "FB_HOST": "192.168.0.6",
    "FB_DATABASE": r"E:\SISTEMA\BASE_CHEQUE\BASE\FATURA.GDB",
    "FB_USER": "usuario",
    "FB_PASSWORD": "segredo",
}


@pytest.fixture
def ambiente_limpo(monkeypatch):
    for k in (
        "FB_HOST", "FB_PORT", "FB_DATABASE", "FB_USER", "FB_PASSWORD", "FB_CHARSET",
        "FB_POOL_SIZE", "CERTGEN_REPOSITORIO", "CERTGEN_APOLICES_MASSA",
    ):  # fmt: skip
        monkeypatch.delenv(k, raising=False)
    # impede que um .env real da raiz seja carregado durante o teste
    monkeypatch.setattr("certgen.config.settings.ARQUIVO_ENV", "/inexistente/.env")
    return monkeypatch


def test_rnf_06_dotenv_nao_sobrescreve_ambiente(tmp_path, ambiente_limpo):
    env = tmp_path / ".env"
    env.write_text("FB_HOST=arquivo\nCERTGEN_REPOSITORIO=api\n# comentario\n", "utf-8")
    ambiente_limpo.setenv("FB_HOST", "ambiente")
    assert carregar_dotenv(env) is True
    assert env_obrigatoria("FB_HOST") == "ambiente"
    assert env_obrigatoria("CERTGEN_REPOSITORIO") == "api"


def test_fedhub_variavel_obrigatoria_ausente_falha_com_mensagem_clara(ambiente_limpo):
    with pytest.raises(ConfiguracaoAusente, match="FB_PASSWORD"):
        env_obrigatoria("FB_PASSWORD")


def test_fedhub_credencial_nao_tem_default(ambiente_limpo):
    for k, v in FB_COMPLETO.items():
        if k != "FB_PASSWORD":
            ambiente_limpo.setenv(k, v)
    with pytest.raises(ConfiguracaoAusente, match="FB_PASSWORD"):
        ConfigFirebird.do_ambiente()


def test_fedhub_nomes_fb_e_defaults_de_porta_charset_pool(ambiente_limpo):
    for k, v in FB_COMPLETO.items():
        ambiente_limpo.setenv(k, v)
    cfg = ConfigFirebird.do_ambiente()
    assert cfg.port == 3050
    assert cfg.charset == "WIN1252"
    assert cfg.pool_size == 5
    assert cfg.dsn == r"192.168.0.6/3050:E:\SISTEMA\BASE_CHEQUE\BASE\FATURA.GDB"


def test_rnf_06_repr_nao_vaza_senha(ambiente_limpo):
    for k, v in FB_COMPLETO.items():
        ambiente_limpo.setenv(k, v)
    assert "segredo" not in repr(ConfigFirebird.do_ambiente())


def test_rn_22_apolices_massa_vem_do_ambiente(ambiente_limpo):
    for k, v in FB_COMPLETO.items():
        ambiente_limpo.setenv(k, v)
    ambiente_limpo.setenv("CERTGEN_APOLICES_MASSA", "4008, 5008,10008")
    cfg = Config.do_ambiente()
    assert cfg.apolices_massa == ("4008", "5008", "10008")
    assert cfg.repositorio == "firebird"
    assert cfg.firebird is not None


def test_adr_01_adaptador_api_nao_exige_variaveis_firebird(ambiente_limpo):
    ambiente_limpo.setenv("CERTGEN_REPOSITORIO", "api")
    cfg = Config.do_ambiente()
    assert cfg.repositorio == "api"
    assert cfg.firebird is None
