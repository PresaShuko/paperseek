from paperseek.config import AgentConfig
from paperseek.config_compiler import compile_agent_config, normalize_search_loop_backend


def test_blank_run_credentials_do_not_erase_environment_values():
    environment = AgentConfig(
        openalex_api_key="environment-openalex",
        llm_api_key="environment-llm",
        llm_model="environment-model",
        llm_base_url="https://environment.example/v1",
    )

    config = compile_agent_config(
        {
            "openalex_api_key": "",
            "llm_api_key": "",
            "llm_model": None,
            "llm_base_url": "",
        },
        environment=environment,
    )

    assert config.openalex_api_key == "environment-openalex"
    assert config.llm_api_key == "environment-llm"
    assert config.llm_model == "environment-model"
    assert config.llm_base_url == "https://environment.example/v1"


def test_provider_change_uses_provider_defaults_when_model_fields_are_absent():
    config = compile_agent_config(
        {"llm_provider": "deepseek"},
        environment=AgentConfig(
            llm_provider="openai",
            llm_api_type="openai_responses",
            llm_model="gpt-5.4-mini",
            llm_base_url="https://api.openai.com/v1",
        ),
    )

    assert config.llm_provider == "deepseek"
    assert config.llm_api_type == "openai_chat"
    assert config.llm_model == "deepseek-v4-flash"
    assert config.llm_base_url == "https://api.deepseek.com"


def test_budget_is_applied_before_explicit_algorithm_overrides():
    config = compile_agent_config(
        {
            "search_budget": "fast",
            "max_iterations": 9,
            "retrieval_lane_limit": 321,
        },
        environment=AgentConfig(),
    )

    assert config.search_budget == "fast"
    assert config.max_iterations == 9
    assert config.retrieval_lane_limit == 321


def test_source_is_selected_before_discipline_normalization():
    config = compile_agent_config(
        {
            "data_source": "openalex",
            "discipline_fields": ["17", "Computer Science"],
        },
        environment=AgentConfig(data_source="wos"),
    )

    assert config.data_source == "openalex"
    assert config.discipline_fields == ("17",)


def test_search_loop_backend_rejects_removed_runtime_backends():
    assert normalize_search_loop_backend("auto") == "auto"
    assert normalize_search_loop_backend("native") == "native"

    try:
        normalize_search_loop_backend("langgraph")
    except ValueError as exc:
        assert "auto or native" in str(exc)
    else:
        raise AssertionError("removed backend must be rejected at request compilation")
