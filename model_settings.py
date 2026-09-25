"""
Per-model settings for the full paper analysis (see docs/agent/decisions/0002, 0004).

- Creator guidance: sampling values shipped with the model, read from LM Studio's hub
  manifest (~/.lmstudio/hub/models/<key>/model.yaml) or, as a fallback, the model folder's
  generation_config.json.
- User overrides: per-model temperature / thinking set from the UI, stored in a JSON file.

Effective report temperature: user override -> creator guidance -> REPORT_TEMPERATURE (.env).
Effective report thinking:    user override -> REPORT_THINKING (.env).
"""
import json
import subprocess
from pathlib import Path

import yaml

import config

LMSTUDIO_HOME = Path.home() / ".lmstudio"


def _normalize_key(model_key):
    return (model_key or "").replace("openai:", "", 1)


def _lms_model_entry(model_key):
    """Returns the `lms ls --json` entry for a model key, or None."""
    try:
        res = subprocess.run(["lms", "ls", "--json"], capture_output=True, text=True, timeout=15)
        for entry in json.loads(res.stdout):
            if entry.get("modelKey") == model_key:
                return entry
    except Exception as e:
        print(f"[-] Error calling lms ls --json: {e}")
    return None


def _read_model_yaml(path):
    """Extracts temperature/top_p/top_k/reasoning from an LM Studio hub model.yaml."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    guidance = {}
    fields = ((data.get("config") or {}).get("operation") or {}).get("fields") or []
    for field in fields:
        key, value = field.get("key"), field.get("value")
        if key == "llm.prediction.temperature":
            guidance["temperature"] = value
        elif key == "llm.prediction.topPSampling":
            guidance["top_p"] = value.get("value") if isinstance(value, dict) else value
        elif key == "llm.prediction.topKSampling":
            guidance["top_k"] = value.get("value") if isinstance(value, dict) else value
    reasoning = (data.get("metadataOverrides") or {}).get("reasoning")
    if reasoning is not None:
        guidance["reasoning"] = bool(reasoning)
    base_keys = [b.get("key", "") for b in data.get("base") or []]
    return guidance, base_keys


def _find_model_dirs(entry, base_keys):
    """Candidate local model folders for a model (direct path, then hub base keys)."""
    models_root = LMSTUDIO_HOME / "models"
    dirs = []
    if entry and entry.get("path"):
        dirs.append(models_root / entry["path"])
    if not models_root.exists():
        return dirs
    wanted = {k.lower() for k in base_keys}
    for publisher in models_root.iterdir():
        if not publisher.is_dir():
            continue
        for model_dir in publisher.iterdir():
            if f"{publisher.name}/{model_dir.name}".lower() in wanted:
                dirs.append(model_dir)
    return dirs


def get_creator_guidance(model_key):
    """
    Returns the model creators' recommended sampling settings, e.g.
    {"temperature": 1.0, "top_p": 0.95, "top_k": 20, "reasoning": True, "source": "model.yaml"}.
    Missing values are omitted; "reasoning" is only present when the manifest declares it.
    """
    model_key = _normalize_key(model_key)
    if not model_key:
        return {}
    guidance, sources, base_keys = {}, [], []

    hub_yaml = LMSTUDIO_HOME / "hub" / "models" / model_key / "model.yaml"
    if hub_yaml.exists():
        try:
            guidance, base_keys = _read_model_yaml(hub_yaml)
            sources.append("model.yaml")
        except Exception as e:
            print(f"[-] Error reading {hub_yaml}: {e}")

    if not all(k in guidance for k in ("temperature", "top_p", "top_k")):
        entry = _lms_model_entry(model_key)
        for model_dir in _find_model_dirs(entry, base_keys):
            gen_config = model_dir / "generation_config.json"
            if not gen_config.exists():
                continue
            try:
                gen = json.loads(gen_config.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"[-] Error reading {gen_config}: {e}")
                continue
            for ours, theirs in (("temperature", "temperature"), ("top_p", "top_p"), ("top_k", "top_k")):
                if ours not in guidance and theirs in gen:
                    guidance[ours] = gen[theirs]
            sources.append("generation_config.json")
            break

    if sources:
        guidance["source"] = " + ".join(sources)
    return guidance


def _load_overrides():
    path = Path(config.MODEL_SETTINGS_PATH)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[-] Error reading {path}: {e}")
        return {}


def get_overrides(model_key):
    return _load_overrides().get(_normalize_key(model_key), {})


def set_overrides(model_key, temperature=None, thinking=None):
    """Stores the user's per-model overrides; None clears that override."""
    model_key = _normalize_key(model_key)
    all_overrides = _load_overrides()
    entry = {}
    if temperature is not None:
        entry["temperature"] = float(temperature)
    if thinking is not None:
        entry["thinking"] = bool(thinking)
    if entry:
        all_overrides[model_key] = entry
    else:
        all_overrides.pop(model_key, None)
    Path(config.MODEL_SETTINGS_PATH).write_text(json.dumps(all_overrides, indent=2) + "\n", encoding="utf-8")
    return entry


def resolve_report_settings(model_key):
    """
    Returns the settings used for the full paper analysis, with where each value came from:
    {"temperature": 1.0, "temperature_source": "creator", "thinking": False, "thinking_source": "env"}
    """
    overrides = get_overrides(model_key)
    if "temperature" in overrides:
        temperature, temperature_source = overrides["temperature"], "override"
    else:
        creator_temp = get_creator_guidance(model_key).get("temperature")
        if creator_temp is not None:
            temperature, temperature_source = float(creator_temp), "creator"
        else:
            temperature, temperature_source = config.REPORT_TEMPERATURE, "env"
    if "thinking" in overrides:
        thinking, thinking_source = overrides["thinking"], "override"
    else:
        thinking, thinking_source = config.REPORT_THINKING, "env"
    return {
        "temperature": temperature,
        "temperature_source": temperature_source,
        "thinking": thinking,
        "thinking_source": thinking_source,
    }
