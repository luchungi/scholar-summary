import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Generator
import urllib.request
import urllib.error

import config

def find_binary(name: str) -> str:
    path = shutil.which(name)
    if path:
        return path
    candidates = [
        Path.home() / f".{name}/bin/{name}",
        Path.home() / ".omlx/bin" / name,
        Path.home() / ".lmstudio/bin" / name,
        Path("/opt/homebrew/bin") / name,
        Path("/usr/local/bin") / name,
    ]
    for c in candidates:
        if c.exists() and os.access(c, os.X_OK):
            return str(c)
    return name

def get_env_file_path() -> Path:
    return Path(__file__).resolve().parents[1] / ".env"

def update_env_file_key(key: str, val: str):
    env_path = get_env_file_path()
    if env_path.exists():
        content = env_path.read_text(encoding="utf-8")
        lines = content.splitlines()
        updated = False
        prefix = f"{key}="
        for idx, line in enumerate(lines):
            if line.strip().startswith(prefix):
                lines[idx] = f"{key}={val}"
                updated = True
                break
        if not updated:
            lines.append(f"{key}={val}")
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

def update_env_framework(framework: str):
    update_env_file_key("LLM_FRAMEWORK", framework.lower())

def update_env_model(framework: str, model_key: str):
    formatted = f"openai:{model_key}" if model_key and not model_key.startswith("openai:") else model_key
    if framework.lower() == "omlx":
        update_env_file_key("OMLX_MODEL", formatted)
    else:
        update_env_file_key("LM_STUDIO_MODEL", formatted)

def format_bytes(num_bytes: Optional[int]) -> str:
    if not num_bytes:
        return "Unknown"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:.2f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.2f} PB"

class LMStudioBackend:
    @staticmethod
    def get_status() -> Dict[str, Any]:
        lms_bin = find_binary("lms")
        try:
            res = subprocess.run([lms_bin, "status"], capture_output=True, text=True, timeout=5)
            if re.search(r'Server:\s*ON', res.stdout, re.IGNORECASE):
                return {"status": "ON"}
            return {"status": "OFF"}
        except Exception as e:
            return {"status": "OFF", "error": str(e)}

    @staticmethod
    def start_server() -> Dict[str, Any]:
        lms_bin = find_binary("lms")
        try:
            res = subprocess.run([lms_bin, "server", "start"], capture_output=True, text=True, timeout=15)
            if res.returncode == 0 or "already running" in res.stdout.lower() or "success" in res.stdout.lower():
                return {"status": "success", "detail": res.stdout.strip()}
            return {"status": "error", "detail": res.stderr or res.stdout}
        except Exception as e:
            return {"status": "error", "detail": str(e)}

    @staticmethod
    def stop_server() -> Dict[str, Any]:
        lms_bin = find_binary("lms")
        try:
            res = subprocess.run([lms_bin, "server", "stop"], capture_output=True, text=True, timeout=15)
            if res.returncode == 0 or "stopped" in res.stdout.lower() or "success" in res.stdout.lower():
                return {"status": "success", "detail": res.stdout.strip()}
            return {"status": "error", "detail": res.stderr or res.stdout}
        except Exception as e:
            return {"status": "error", "detail": str(e)}

    @staticmethod
    def get_loaded_model() -> Optional[str]:
        lms_bin = find_binary("lms")
        try:
            res = subprocess.run([lms_bin, "ps"], capture_output=True, text=True, timeout=10)
            lines = res.stdout.splitlines()
            for line in lines:
                line_str = line.strip()
                if not line_str or line_str.startswith("IDENTIFIER") or "waking up" in line_str.lower() or "no models" in line_str.lower():
                    continue
                parts = line_str.split()
                if parts:
                    return parts[0]
        except Exception as e:
            print(f"[-] Error calling lms ps: {e}")
        return None

    @staticmethod
    def unload_models() -> Dict[str, Any]:
        lms_bin = find_binary("lms")
        try:
            res = subprocess.run([lms_bin, "unload", "--all"], capture_output=True, text=True, timeout=15)
            return {"status": "success", "detail": res.stdout.strip()}
        except Exception as e:
            return {"status": "error", "detail": str(e)}

    @staticmethod
    def list_models() -> List[Dict[str, Any]]:
        lms_bin = find_binary("lms")
        loaded_in_mem = LMStudioBackend.get_loaded_model()
        try:
            res_ls = subprocess.run([lms_bin, "ls"], capture_output=True, text=True, timeout=15)
            lines = res_ls.stdout.splitlines()
            models = []
            for line in lines:
                if "Local" in line:
                    parts = [p.strip() for p in line.split("  ") if p.strip()]
                    if len(parts) >= 4:
                        key_with_variant = parts[0]
                        key = key_with_variant.split(" (")[0]
                        size = parts[2]
                        is_loaded = (loaded_in_mem == key) if loaded_in_mem else ("✓ LOADED" in line or "LOADED" in line)
                        if "embedding" not in key.lower():
                            models.append({
                                "key": key,
                                "size": size,
                                "loaded": is_loaded
                            })
            return models
        except Exception as e:
            print(f"[-] Error calling lms ls: {e}")
            curr = config.LM_STUDIO_MODEL.replace("openai:", "")
            return [{"key": curr, "size": "Unknown", "loaded": True}] if curr else []

class OMLXBackend:
    @staticmethod
    def _base_url() -> str:
        return config.OMLX_BASE_URL.rstrip("/")

    @staticmethod
    def _headers() -> Dict[str, str]:
        key = config.get_omlx_api_key()
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    @staticmethod
    def get_status() -> Dict[str, Any]:
        # Strip /v1 if present to ping /health
        base = OMLXBackend._base_url().replace("/v1", "")
        url = f"{base}/health"
        req = urllib.request.Request(url, headers=OMLXBackend._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    return {"status": "ON"}
                return {"status": "OFF"}
        except urllib.error.HTTPError as e:
            # 401 or 403 means server process is running and responding
            if e.code in (401, 403, 200):
                return {"status": "ON"}
            return {"status": "OFF"}
        except Exception:
            return {"status": "OFF"}

    @staticmethod
    def start_server() -> Dict[str, Any]:
        omlx_bin = find_binary("omlx")
        try:
            res = subprocess.run([omlx_bin, "start"], capture_output=True, text=True, timeout=15)
            if res.returncode == 0 or "running" in res.stdout.lower() or "started" in res.stdout.lower():
                return {"status": "success", "detail": res.stdout.strip()}
            return {"status": "error", "detail": res.stderr or res.stdout}
        except Exception as e:
            return {"status": "error", "detail": str(e)}

    @staticmethod
    def stop_server() -> Dict[str, Any]:
        omlx_bin = find_binary("omlx")
        try:
            res = subprocess.run([omlx_bin, "stop"], capture_output=True, text=True, timeout=15)
            if res.returncode == 0 or "stopped" in res.stdout.lower():
                return {"status": "success", "detail": res.stdout.strip()}
            return {"status": "error", "detail": res.stderr or res.stdout}
        except Exception as e:
            return {"status": "error", "detail": str(e)}

    @staticmethod
    def get_loaded_model() -> Optional[str]:
        url = f"{OMLXBackend._base_url()}/models/status"
        req = urllib.request.Request(url, headers=OMLXBackend._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for model in data.get("models", []):
                    if model.get("loaded"):
                        return model.get("id")
        except Exception as e:
            print(f"[-] Error querying oMLX models status: {e}")
        return None

    @staticmethod
    def unload_models() -> Dict[str, Any]:
        loaded = OMLXBackend.get_loaded_model()
        if not loaded:
            return {"status": "success", "detail": "No model loaded"}
        url = f"{OMLXBackend._base_url()}/models/{loaded}/unload"
        req = urllib.request.Request(url, headers=OMLXBackend._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return {"status": "success", "detail": f"Unloaded {loaded}"}
        except Exception as e:
            return {"status": "error", "detail": str(e)}

    @staticmethod
    def list_models() -> List[Dict[str, Any]]:
        url = f"{OMLXBackend._base_url()}/models/status"
        req = urllib.request.Request(url, headers=OMLXBackend._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = []
                for m in data.get("models", []):
                    if not m.get("is_helper"):
                        models.append({
                            "key": m.get("id"),
                            "size": format_bytes(m.get("estimated_size")),
                            "loaded": bool(m.get("loaded")),
                            "path": m.get("model_path"),
                            "thinking_default": m.get("thinking_default"),
                        })
                return models
        except Exception as e:
            print(f"[-] Error listing oMLX models: {e}")
            curr = config.OMLX_MODEL.replace("openai:", "")
            return [{"key": curr, "size": "Unknown", "loaded": True}] if curr else []

    @staticmethod
    def load_model(model_key: str) -> Dict[str, Any]:
        url = f"{OMLXBackend._base_url()}/models/{model_key}/load"
        req = urllib.request.Request(url, headers=OMLXBackend._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return {"status": "success", "detail": resp.read().decode("utf-8")}
        except Exception as e:
            raise RuntimeError(f"oMLX load model error: {e}")

class FrameworkManager:
    @classmethod
    def get_backend(cls, framework: Optional[str] = None):
        fw = (framework or config.get_active_framework()).lower()
        if fw == "omlx":
            return OMLXBackend
        return LMStudioBackend

    @classmethod
    def get_server_status(cls, framework: Optional[str] = None) -> Dict[str, Any]:
        return cls.get_backend(framework).get_status()

    @classmethod
    def start_server(cls, framework: Optional[str] = None) -> Dict[str, Any]:
        return cls.get_backend(framework).start_server()

    @classmethod
    def stop_server(cls, framework: Optional[str] = None) -> Dict[str, Any]:
        return cls.get_backend(framework).stop_server()

    @classmethod
    def get_loaded_model(cls, framework: Optional[str] = None) -> Optional[str]:
        return cls.get_backend(framework).get_loaded_model()

    @classmethod
    def unload_models(cls, framework: Optional[str] = None) -> Dict[str, Any]:
        return cls.get_backend(framework).unload_models()

    @classmethod
    def list_models(cls, framework: Optional[str] = None) -> List[Dict[str, Any]]:
        return cls.get_backend(framework).list_models()

    @classmethod
    def stream_load_model(cls, model_key: str, framework: Optional[str] = None) -> Generator[str, None, None]:
        fw = (framework or config.get_active_framework()).lower()
        yield f"data: Checking currently loaded models in {fw.upper()} memory...\n\n"
        backend = cls.get_backend(fw)
        loaded = backend.get_loaded_model()

        if model_key == "none":
            if loaded:
                yield f"data: Active model in memory is '{loaded}'. Unloading...\n\n"
                backend.unload_models()
                yield "data: Unloaded successfully.\n\n"
            else:
                yield "data: No active model in memory to unload.\n\n"
            config.set_active_model("")
            update_env_model(fw, "")
            yield "data: [SUCCESS]\n\n"
            return

        if loaded == model_key:
            yield f"data: Model '{model_key}' is already loaded in memory. Skipping reload.\n\n"
            config.set_active_model(model_key)
            update_env_model(fw, model_key)
            yield "data: [SUCCESS]\n\n"
            return

        if loaded:
            yield f"data: Active model in memory is '{loaded}'. Unloading first...\n\n"
            backend.unload_models()
            yield "data: Unloaded successfully.\n\n"
        else:
            yield "data: No models currently active in memory.\n\n"

        yield f"data: Loading '{model_key}' into {fw.upper()} memory...\n\n"

        if fw == "omlx":
            try:
                OMLXBackend.load_model(model_key)
                config.set_active_model(model_key)
                update_env_model(fw, model_key)
                yield f"data: Successfully loaded model '{model_key}'!\n\n"
                yield "data: [SUCCESS]\n\n"
            except Exception as e:
                yield f"data: [ERROR] Failed to load model in oMLX: {e}\n\n"
        else:
            # LM Studio subprocess streaming
            lms_bin = find_binary("lms")
            cmd = f"{lms_bin} load {model_key} -y"
            try:
                process = subprocess.Popen(
                    cmd,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1
                )
                while True:
                    line = process.stdout.readline()
                    if not line:
                        break
                    line_clean = line.strip()
                    if line_clean:
                        yield f"data: {line_clean}\n\n"

                process.wait()
                if process.returncode == 0:
                    config.set_active_model(model_key)
                    update_env_model(fw, model_key)
                    yield f"data: Successfully loaded model '{model_key}'!\n\n"
                    yield "data: [SUCCESS]\n\n"
                else:
                    yield f"data: [ERROR] Failed to load model. Return code: {process.returncode}\n\n"
            except Exception as e:
                yield f"data: [ERROR] Exception during model load: {e}\n\n"

    @classmethod
    def stream_switch_framework(cls, target_framework: str) -> Generator[str, None, None]:
        target = target_framework.lower().strip()
        if target not in ("lmstudio", "omlx"):
            yield f"data: [ERROR] Unknown framework '{target}'. Supported: lmstudio, omlx\n\n"
            return

        current = config.get_active_framework().lower()
        if current == target:
            yield f"data: Framework is already '{target}'. No switch needed.\n\n"
            yield "data: [SUCCESS]\n\n"
            return

        # 1. Check if model is loaded in current framework
        yield f"data: Step 1/4: Checking active model in {current.upper()}...\n\n"
        current_backend = cls.get_backend(current)
        loaded = current_backend.get_loaded_model()
        if loaded:
            yield f"data: Unloading active model '{loaded}' from {current.upper()}...\n\n"
            current_backend.unload_models()
            yield "data: Active model unloaded.\n\n"
        else:
            yield f"data: No model loaded in {current.upper()}.\n\n"

        # 2. Stop current server
        yield f"data: Step 2/4: Stopping {current.upper()} server...\n\n"
        current_backend.stop_server()
        time.sleep(1.0)
        yield f"data: {current.upper()} server stopped.\n\n"

        # 3. Switch framework config & start target server
        yield f"data: Step 3/4: Switching configuration to {target.upper()} and starting server...\n\n"
        config.set_active_framework(target)
        update_env_framework(target)

        target_backend = cls.get_backend(target)
        start_res = target_backend.start_server()
        yield f"data: Initiated start for {target.upper()} server: {start_res.get('detail', '')}\n\n"

        # Wait for server to report ON
        is_online = False
        for attempt in range(15):
            time.sleep(1.0)
            status_data = target_backend.get_status()
            if status_data.get("status") == "ON":
                is_online = True
                break
            yield f"data: Waiting for {target.upper()} server to become healthy (attempt {attempt + 1}/15)...\n\n"

        if is_online:
            yield f"data: {target.upper()} server is ONLINE.\n\n"
        else:
            yield f"data: Warning: {target.upper()} server did not report online in time. You can start it manually.\n\n"

        # 4. Check if a model is already loaded in target framework
        yield f"data: Step 4/4: Checking loaded models in {target.upper()}...\n\n"
        target_loaded = target_backend.get_loaded_model()
        if target_loaded:
            yield f"data: Found already loaded model '{target_loaded}' in {target.upper()}.\n\n"
            config.set_active_model(target_loaded)
            update_env_model(target, target_loaded)
        else:
            yield f"data: No model currently loaded in {target.upper()}.\n\n"
            config.set_active_model("")
            update_env_model(target, "")

        yield f"data: Framework successfully switched to {target.upper()}!\n\n"
        yield "data: [SUCCESS]\n\n"
