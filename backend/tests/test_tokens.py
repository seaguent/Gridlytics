from app.tokens import generate_token, hash_token


def test_generate_token_produces_unique_high_entropy_values():
    tokens = {generate_token() for _ in range(100)}
    assert len(tokens) == 100
    assert all(len(token) >= 32 for token in tokens)


def test_hash_token_is_deterministic():
    token = "some-fixed-token-value"
    assert hash_token(token) == hash_token(token)


def test_hash_token_matches_known_sha256_value():
    # sha256("hello") is a well-known test vector.
    assert hash_token("hello") == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"


def test_hash_token_differs_for_different_inputs():
    assert hash_token("token-a") != hash_token("token-b")
