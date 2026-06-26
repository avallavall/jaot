"""Unit tests for BYOK crypto + client resolution (app/services/llm/byok.py)."""

from types import SimpleNamespace

from app.services.llm import byok


class TestEncryption:
    def test_encrypt_decrypt_round_trip(self):
        plaintext = "sk-ant-api03-abcdef1234567890"
        token = byok.encrypt_api_key(plaintext)
        assert token != plaintext  # ciphertext, not the raw key
        assert byok.decrypt_api_key(token) == plaintext

    def test_decrypt_none_returns_none(self):
        assert byok.decrypt_api_key(None) is None
        assert byok.decrypt_api_key("") is None

    def test_decrypt_garbage_returns_none(self):
        # A non-Fernet token must never raise — it is treated as "no key".
        assert byok.decrypt_api_key("not-a-valid-fernet-token") is None

    def test_mask_api_key(self):
        assert byok.mask_api_key("sk-ant-api03-abcd1234") == "sk-ant-…1234"
        assert byok.mask_api_key(None) is None
        assert byok.mask_api_key("") is None


class TestResolution:
    def test_org_without_key_resolves_platform(self):
        org = SimpleNamespace(anthropic_api_key_encrypted=None)
        assert byok.get_org_api_key(org) is None
        assert byok.org_has_byok(org) is False
        client, is_byok = byok.resolve_anthropic_client(org)
        assert client is None
        assert is_byok is False

    def test_org_with_key_resolves_byok(self):
        plaintext = "sk-ant-api03-resolve-test-key-1234"
        org = SimpleNamespace(anthropic_api_key_encrypted=byok.encrypt_api_key(plaintext))
        assert byok.get_org_api_key(org) == plaintext
        assert byok.org_has_byok(org) is True
        client, is_byok = byok.resolve_anthropic_client(org)
        assert client is not None  # an AsyncAnthropic built from the org key
        assert is_byok is True
