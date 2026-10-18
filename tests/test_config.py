import pytest

from encorlab import config


def test_from_env_defaults():
    s = config.from_env({"ENCOR_USE_KEYRING": "0"})
    assert s.verify_tls is True and s.node_limit == 20 and s.platform == "iol" and s.console_backend == "ssh"


def test_from_env_values():
    s = config.from_env({"CML_URL": "https://cml.ts.net/", "CML_USERNAME": "d", "CML_PASSWORD": "pw",
                         "CML_VERIFY_SSL": "false", "ENCOR_PLATFORM": "iosv", "ENCOR_NODE_LIMIT": "5"})
    assert s.cml_url == "https://cml.ts.net" and s.verify_tls is False and s.platform == "iosv" and s.node_limit == 5
    assert config.from_env({"CML_VERIFY_SSL": "C:\\ca.pem", "ENCOR_USE_KEYRING": "0"}).verify_tls == "C:\\ca.pem"


def test_secrets_never_in_repr_or_public():
    s = config.Settings(cml_url="https://x", username="u", password="TOPSECRET")
    assert "TOPSECRET" not in repr(s) and "TOPSECRET" not in str(s.public_dict())
    assert s.public_dict()["password_set"] is True


def test_store_update_keeps_secret_on_blank():
    st = config.SettingsStore(config.Settings(cml_url="https://x", username="u", password="pw"))
    st.update(password="", node_limit="10")
    assert st.get().password == "pw" and st.get().node_limit == 10


def test_store_validation():
    st = config.SettingsStore(config.Settings())
    with pytest.raises(ValueError):
        st.update(platform="nxos")
    with pytest.raises(ValueError):
        st.update(cml_url="ftp://x")
    with pytest.raises(ValueError):
        st.update(bogus=1)


def test_keyring_lookup(monkeypatch):
    monkeypatch.setattr(config, "keyring_get", lambda u: "fromkeyring")
    s = config.from_env({"CML_URL": "https://x", "CML_USERNAME": "u"})
    assert s.password == "fromkeyring"
