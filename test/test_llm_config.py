"""Test LLM config loading and optional live generation."""
import argparse
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.config.settings import load_config
from src.extraction.llm_client import LLMClient
from src.extraction.providers.factory import create_provider


def test_config_load():
    """Verify config.yaml parses and resolves defaults."""
    app = load_config()
    llm = app.llm
    print("LLM configuration")
    print("=" * 40)
    print(f"  provider:     {llm.provider}")
    print(f"  model:        {llm.model}")
    print(f"  base_url:     {llm.resolved_base_url()}")
    print(f"  api_key_env:  {llm.resolved_api_key_env()}")
    print(f"  timeout:      {llm.timeout_seconds}s")
    print(f"  temperature:  {llm.temperature}")
    print(f"  max_tokens:   {llm.max_new_tokens}")
    provider = create_provider(llm)
    print(f"  provider class: {type(provider).__name__}")
    print("=" * 40)
    print("Config load: OK")
    return app


def test_live_generate():
    """Call the configured LLM with a minimal prompt."""
    client = LLMClient.from_config()
    prompt = 'Reply with exactly one word: OK'
    print("\nLive LLM test")
    print("=" * 40)
    print(f"Sending prompt: {prompt!r}")
    response = client.generate(prompt=prompt, max_new_tokens=16).text
    print(f"Response: {response!r}")
    print("=" * 40)
    print("Live generate: OK")
    return response


def main():
    parser = argparse.ArgumentParser(description="Test LLM config")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Call the configured LLM (requires Ollama/LM Studio running or API key)",
    )
    args = parser.parse_args()

    try:
        test_config_load()
        if args.live:
            test_live_generate()
    except Exception as e:
        print(f"\nFailed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
