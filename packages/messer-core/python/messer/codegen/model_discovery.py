from pathlib import Path

import yaml

_MODELS_YAML = Path(__file__).parent.parent / "models.yaml"

_PROVIDER_LOGOS = {
    "anthropic": "https://usercontent.messer.local/assets/anthropic_favicon.svg",
    "openai": "https://usercontent.messer.local/assets/openai_favicon.svg",
    "google": "https://usercontent.messer.local/assets/google_favicon.svg",
    "togetherai": "https://usercontent.messer.local/assets/togetherai_favicon.svg",
    "xai": "https://usercontent.messer.local/assets/xai_favicon.svg",
    "groq": "https://usercontent.messer.local/assets/groq_favicon.svg",
    "fireworks": "https://usercontent.messer.local/assets/fireworks_favicon.svg",
    "xiaomi": "https://usercontent.messer.local/assets/xiaomi_favicon.svg",
    "byteplus": "https://usercontent.messer.local/assets/byteplus_favicon.svg",
    "cerebras": "https://usercontent.messer.local/assets/cerebras_favicon.svg",
    "sambanova": "https://usercontent.messer.local/assets/sambanova_favicon.svg",
    "moonshot": "https://usercontent.messer.local/assets/moonshot_favicon.svg",
}


def get_models() -> list[dict]:
    """Return all supported LLM models from models.yaml.

    Each entry contains: id, provider, display_name, description, input_price,
    output_price, context_window, capabilities, and optional availability fields
    (requires_activation, dedicated_only, notes).
    """
    with _MODELS_YAML.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("models", [])


def get_provider_summaries() -> list[dict]:
    """Return provider summaries with model counts, sorted by count descending."""
    groups: dict[str, dict] = {}
    for model in get_models():
        provider = model["provider"]
        if provider not in groups:
            groups[provider] = {
                "name": provider,
                "logo": _PROVIDER_LOGOS.get(provider),
                "model_count": 0,
            }
        groups[provider]["model_count"] += 1
    return sorted(groups.values(), key=lambda g: g["model_count"], reverse=True)
