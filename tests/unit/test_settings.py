"""Fase 0 — leitura de configuracao (RNF-06, ADR-01, RN-22)."""

from certgen.config.settings import Config, carregar_dotenv


def test_rnf_06_dotenv_nao_sobrescreve_ambiente(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("FIREBIRD_HOST=arquivo\nCERTGEN_REPOSITORIO=api\n# comentario\n", "utf-8")
    monkeypatch.setenv("FIREBIRD_HOST", "ambiente")
    monkeypatch.delenv("CERTGEN_REPOSITORIO", raising=False)
    aplicadas = carregar_dotenv(env)
    assert aplicadas == {"CERTGEN_REPOSITORIO": "api"}


def test_rn_22_apolices_massa_vem_do_ambiente(monkeypatch):
    monkeypatch.setenv("CERTGEN_APOLICES_MASSA", "4008, 5008,10008")
    monkeypatch.setenv("CERTGEN_REPOSITORIO", "firebird")
    cfg = Config.do_ambiente()
    assert cfg.apolices_massa == ("4008", "5008", "10008")
    assert cfg.repositorio == "firebird"


def test_fase_0_config_incompleta_e_detectavel(monkeypatch):
    for k in ("FIREBIRD_DATABASE", "FIREBIRD_USER", "FIREBIRD_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.chdir("/")  # evita ler um .env real
    assert Config.do_ambiente().firebird.completa() is False
