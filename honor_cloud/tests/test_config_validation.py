from load_module import load

config_validation = load("config_validation.py")


def test_validate_ok():
    assert config_validation.validate_credentials("http://127.0.0.1:8787", "u", "p") == {}


def test_validate_missing_url():
    assert config_validation.validate_credentials("", "u", "p")["base"] == "base_url_required"


def test_validate_bad_url():
    assert config_validation.validate_credentials("ftp://x", "u", "p")["base"] == "invalid_url"
