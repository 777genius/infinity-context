from infinity_context_server.config import Settings


def test_real_provider_disabled_in_test_memory_scope() -> None:
    settings = Settings(
        deploy_profile="test",
        embeddings_enabled=True,
        embeddings_provider="openai",
        openai_api_key="test-key",
    )

    try:
        settings.validate_for_startup()
    except RuntimeError as exc:
        assert "test deploy profile cannot use external adapters" in str(exc)
    else:
        raise AssertionError("Expected test deploy profile external provider validation to fail")
