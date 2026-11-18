#!/usr/bin/env python
"""
Concurrency benchmark for full paper reviews (docs/agent/decisions/0013).

    .venv/bin/python scripts/bench_concurrency.py prepare    # pick and cache the papers (network only)
    .venv/bin/python scripts/bench_concurrency.py run        # unattended, ~2h, VS Code closed
    .venv/bin/python scripts/bench_concurrency.py probe      # ~45 min, thinking on (decision 0021)

`prepare` picks already-reviewed papers from the app database with a spread of lengths
(4 short, 1 mid, 1 long), downloads their text once and caches it under bench/cache/.

`run` backs up ~/.omlx/settings.json, then for each configuration applies its oMLX
settings, restarts oMLX, loads the model, reviews the cached papers through the app's
ReviewScheduler (thinking off), and records timings, aborts and memory. The original
settings are restored and oMLX restarted at the end, also after ctrl-C or an error.
Results go to bench/results/<timestamp>/ (results.json, summary.md, reports, log).

`probe` answers three questions on the current model with thinking on, using the app's
real review prompt, oMLX at memory_guard_tier=aggressive with its cache off:
  A. Is processing two prompts at once faster than one after the other?
  B. How fast do 1..N reviews generate in total once all N are generating?
  C. How fast does oMLX give memory back after a long review, and is a short pause
     before the next prompt enough?
Results go to bench/results/<timestamp>/ (probe.json, probe.md, log).

Run it under normal conditions: VS Code and other heavy apps closed, the app backend
idle (no batch running). Only Safari, as during a normal batch.
"""

import argparse
import json
import os
import re
import sqlite3
import subprocess
import signal
import sys
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import config
import agent
import model_settings
import paper_retriever
from backend.framework_manager import find_binary
from backend.review_scheduler import ReviewScheduler, estimate_review_tokens

BENCH_DIR = ROOT / "bench"
CACHE_FILE = BENCH_DIR / "cache" / "papers.json"
RESULTS_DIR = BENCH_DIR / "results"
OMLX_SETTINGS = Path.home() / ".omlx" / "settings.json"
OMLX_LOG = Path.home() / ".omlx" / "logs" / "server.log"

# Estimated review tokens (prompt + output reserve) per bucket, and how many of each.
BUCKETS = [("short", 12_000, 20_000, 4), ("mid", 24_000, 32_000, 1), ("long", 34_000, 60_000, 1)]

# Fraction of the oMLX ceiling at which each memory guard tier aborts requests
# (omlx/process_memory_enforcer.py, _HARD_THRESHOLD_BY_TIER).
HARD_THRESHOLD = {"safe": 0.95, "balanced": 0.95, "aggressive": 0.98, "custom": 0.97}


@dataclass
class BenchConfig:
    name: str
    concurrency: int
    tier: str
    cache: bool
    chunked_prefill: bool


CONFIGS = [
    BenchConfig("c1-balanced", 1, "balanced", True, False),
    BenchConfig("c2-balanced", 2, "balanced", True, False),
    BenchConfig("c2-aggressive", 2, "aggressive", True, False),
    BenchConfig("c2-aggressive-nocache", 2, "aggressive", False, False),
    BenchConfig("c2-aggressive-chunked", 2, "aggressive", True, True),
]


def log(msg=""):
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# prepare
# ---------------------------------------------------------------------------

def access_note(retrieval):
    source_label = ("PDF (downloaded and parsed)" if retrieval["source"] == "pdf"
                    else "HTML scrape of the landing page (full PDF may not have been accessible)")
    note = f"Text obtained via {source_label}; {retrieval['raw_chars']} characters extracted"
    return note + ("; middle of the paper truncated to fit the context budget." if retrieval["truncated"] else ".")


def cmd_prepare(args):
    if CACHE_FILE.exists() and not args.force:
        log(f"{CACHE_FILE} already exists; use --force to pick papers again.")
        return
    # Never learn or rewrite URL rules from the benchmark.
    paper_retriever.set_domain_rule = lambda *a, **k: None
    interests = Path(config.INTERESTS_FILE).read_text(encoding="utf-8")

    con = sqlite3.connect(f"file:{ROOT / 'scholar_summary.db'}?mode=ro", uri=True)
    rows = con.execute("SELECT title, url FROM paper WHERE status='success' "
                       "ORDER BY date_processed DESC").fetchall()
    con.close()

    need = {name: n for name, _, _, n in BUCKETS}
    picked = []
    for title, url in rows:
        if not any(need.values()):
            break
        log(f"Fetching: {title[:70]}")
        try:
            retrieval = paper_retriever.retrieve_paper(url)
        except Exception as e:
            log(f"  [-] {e}")
            continue
        if not retrieval or retrieval["source"] != "pdf":
            log("  [-] no PDF text, skipped")
            continue
        # Buckets were drawn with the 2k thinking-off reserve; keep them comparable.
        tokens = estimate_review_tokens(retrieval["text"], interests, thinking=False)
        bucket = next((name for name, lo, hi, _ in BUCKETS if lo <= tokens <= hi), None)
        log(f"  ~{tokens} tokens -> {bucket or 'no bucket'}")
        if bucket and need[bucket] > 0:
            need[bucket] -= 1
            picked.append({"title": title, "url": url, "bucket": bucket, "est_tokens": tokens,
                           "paper_text": retrieval["text"], "access_info": access_note(retrieval)})
    if any(need.values()):
        log(f"[!] Could not fill every bucket, still missing: {need}")
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(picked, indent=1), encoding="utf-8")
    log(f"\nCached {len(picked)} paper(s) to {CACHE_FILE}:")
    for p in sorted(picked, key=lambda p: -p["est_tokens"]):
        log(f"  {p['bucket']:5} ~{p['est_tokens']:6} tokens  {p['title'][:70]}")


# ---------------------------------------------------------------------------
# oMLX control
# ---------------------------------------------------------------------------

class OMLX:
    def __init__(self):
        self.v1 = config.OMLX_BASE_URL.rstrip("/")
        self.base = re.sub(r"/v1$", "", self.v1)
        self.port = int(re.search(r":(\d+)", self.base).group(1))
        self.model = config.OMLX_MODEL.replace("openai:", "")
        self.bin = find_binary("omlx")
        self.proc = None
        self.serve_log = None

    def headers(self):
        key = config.get_omlx_api_key()
        return {"Authorization": f"Bearer {key}"} if key else {}

    def is_up(self):
        try:
            r = requests.get(f"{self.base}/health", headers=self.headers(), timeout=3)
            return r.status_code in (200, 401, 403)
        except requests.RequestException:
            return False

    def status(self):
        try:
            r = requests.get(f"{self.base}/api/status", headers=self.headers(), timeout=5)
            return r.json() if r.ok else None
        except (requests.RequestException, ValueError):
            return None

    def cli(self, command, timeout=180):
        res = subprocess.run([self.bin, command], capture_output=True, text=True, timeout=timeout)
        log(f"  omlx {command}: {(res.stdout or res.stderr).strip()[:200]}")

    def wait_up(self, timeout=240):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.is_up() and self.status() is not None:
                return
            time.sleep(2)
        raise RuntimeError(f"oMLX did not come up within {timeout}s")

    def stop(self):
        """Stop our `omlx serve` child, or an app-managed server; then free the port."""
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=60)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=30)
        self.proc = None
        if self.pid():
            self.cli("stop")
        deadline = time.time() + 60
        while time.time() < deadline and self.pid():
            time.sleep(1)
        pid = self.pid()
        if pid:
            # `omlx restart` can leave a server oMLX.app no longer tracks (2026-11-01 run).
            log(f"  Port {self.port} still held by PID {pid} after `omlx stop`; terminating it.")
            os.kill(pid, signal.SIGTERM)
            deadline = time.time() + 30
            while time.time() < deadline and self.pid():
                time.sleep(1)
            if self.pid():
                os.kill(pid, signal.SIGKILL)
                time.sleep(2)
        if self.pid():
            raise RuntimeError(f"could not free port {self.port}")

    def start_serve(self, log_path):
        """
        Run `omlx serve` as our own child process. oMLX.app's control socket proved
        unreliable right after a stop (`Expecting value`, server never started), so
        the benchmark owns its server. It reads ~/.omlx/settings.json at startup.
        """
        settings = json.loads(OMLX_SETTINGS.read_text(encoding="utf-8"))
        cmd = [self.bin, "serve", "--port", str(self.port)]
        model_dir = settings.get("model", {}).get("model_dir")
        if model_dir:
            cmd += ["--model-dir", model_dir]
        self.serve_log = open(log_path, "a", encoding="utf-8")
        self.proc = subprocess.Popen(cmd, stdout=self.serve_log, stderr=subprocess.STDOUT,
                                     start_new_session=True)
        log(f"  Started `omlx serve` (PID {self.proc.pid}), output in {log_path.name}")

    def restart(self, expect_tier=None, serve_log=None):
        """Stop and start oMLX, and confirm a new server process read the settings file."""
        old_pid = self.pid()
        offset = log_size()
        self.stop()
        if serve_log is not None:
            self.start_serve(serve_log)
        else:
            self.cli("start")
        deadline = time.time() + 240
        while time.time() < deadline:
            if self.proc is not None and self.proc.poll() is not None:
                raise RuntimeError(f"`omlx serve` exited with code {self.proc.returncode}; see {serve_log}")
            if self.is_up() and self.status() is not None:
                break
            time.sleep(2)
        else:
            raise RuntimeError("oMLX did not come up within 240s")
        new_pid = self.pid()
        if new_pid is None or new_pid == old_pid:
            raise RuntimeError(f"oMLX did not restart (PID {old_pid} -> {new_pid})")
        text = read_log_since(offset)
        if serve_log is not None and Path(serve_log).exists():
            text += Path(serve_log).read_text(encoding="utf-8", errors="replace")
        tiers = re.findall(r"Memory guard tier: (\w+)", text)
        if expect_tier and (not tiers or tiers[-1] != expect_tier):
            raise RuntimeError(f"oMLX restarted with memory guard tier {tiers[-1] if tiers else 'unknown'}, "
                               f"expected {expect_tier}")
        log(f"  Restarted oMLX: PID {old_pid} -> {new_pid}, memory guard tier {tiers[-1] if tiers else '?'}")

    def load_model(self):
        log(f"  Loading {self.model}...")
        r = requests.post(f"{self.v1}/models/{self.model}/load", headers=self.headers(), timeout=900)
        r.raise_for_status()
        deadline = time.time() + 900
        while time.time() < deadline:
            st = self.status() or {}
            if self.model in (st.get("loaded_models") or []):
                return
            time.sleep(2)
        raise RuntimeError("model did not report loaded")

    def warm_up(self):
        r = requests.post(f"{self.v1}/chat/completions", headers=self.headers(), timeout=300, json={
            "model": self.model, "max_tokens": 8, "temperature": 0.0,
            "messages": [{"role": "user", "content": "Reply with the word ready."}],
            "enable_thinking": False,
        })
        r.raise_for_status()

    def pid(self):
        res = subprocess.run(["lsof", "-nP", "-t", f"-iTCP:{self.port}", "-sTCP:LISTEN"],
                             capture_output=True, text=True)
        pids = res.stdout.split()
        return int(pids[0]) if pids else None


def log_size():
    return OMLX_LOG.stat().st_size if OMLX_LOG.exists() else 0


def read_log_since(offset):
    if not OMLX_LOG.exists():
        return ""
    with open(OMLX_LOG, "r", encoding="utf-8", errors="replace") as f:
        if OMLX_LOG.stat().st_size >= offset:   # else the log rotated; read it all
            f.seek(offset)
        return f.read()


def apply_settings(original, cfg):
    s = json.loads(json.dumps(original))
    s.setdefault("memory", {})["memory_guard_tier"] = cfg.tier
    s.setdefault("cache", {})["enabled"] = cfg.cache
    s.setdefault("scheduler", {})["chunked_prefill"] = cfg.chunked_prefill
    OMLX_SETTINGS.write_text(json.dumps(s, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# measurement
# ---------------------------------------------------------------------------

GB = 1024 ** 3


def footprint_gb(pid):
    if not pid:
        return None
    res = subprocess.run(["footprint", "-p", str(pid)], capture_output=True, text=True, timeout=20)
    m = re.search(r"Footprint:\s*([\d.]+)\s*(KB|MB|GB)", res.stdout)
    if not m:
        return None
    return float(m.group(1)) / {"KB": 1024 ** 2, "MB": 1024, "GB": 1}[m.group(2)]


def vm_stats_gb():
    out = subprocess.run(["vm_stat"], capture_output=True, text=True).stdout
    page = int(re.search(r"page size of (\d+)", out).group(1))

    def pages(label):
        m = re.search(rf"{label}:\s+(\d+)", out)
        return int(m.group(1)) * page / GB if m else 0.0

    return {"free": pages("Pages free") + pages("Pages speculative"),
            "inactive": pages("Pages inactive"),
            "compressed": pages("Pages occupied by compressor")}


def swap_used_gb():
    out = subprocess.run(["sysctl", "vm.swapusage"], capture_output=True, text=True).stdout
    m = re.search(r"used = ([\d.]+)M", out)
    return float(m.group(1)) / 1024 if m else 0.0


class MemorySampler(threading.Thread):
    def __init__(self, omlx, interval=3.0):
        super().__init__(daemon=True)
        self.omlx, self.interval = omlx, interval
        self.samples = []
        self._halt = threading.Event()

    def run(self):
        t0 = time.time()
        pid = self.omlx.pid()
        while not self._halt.is_set():
            try:
                st = self.omlx.status() or {}
                ceiling = st.get("model_memory_max")
                self.samples.append({
                    "t": round(time.time() - t0, 1),
                    "mono": time.monotonic(),
                    "footprint_gb": footprint_gb(pid),
                    "ceiling_gb": ceiling / GB if ceiling else None,
                    "active_requests": st.get("active_requests"),
                    "swap_used_gb": swap_used_gb(),
                    **vm_stats_gb(),
                })
            except Exception as e:
                self.samples.append({"t": round(time.time() - t0, 1), "error": str(e)})
            self._halt.wait(self.interval)

    def stop(self):
        self._halt.set()
        self.join(timeout=30)


COMPLETION_RE = re.compile(r"Chat completion: model=[^,]+, (\d+) tokens in ([\d.]+)s.*?prompt: (\d+)"
                           r"(?:.*?stream_model_ttft=([\d.]+)s)?")


def parse_server_log(text):
    completions = [{"completion_tokens": int(m.group(1)), "total_s": float(m.group(2)),
                    "prompt_tokens": int(m.group(3)),
                    "ttft_s": float(m.group(4)) if m.group(4) else None}
                   for m in COMPLETION_RE.finditer(text)]
    aborted = sum(int(n) for n in re.findall(r"Aborted (\d+) requests due to memory pressure", text))
    ceilings = [float(x) for x in re.findall(r"dynamic ceiling ([\d.]+)\s*GB", text)]
    return {
        "completions": [c for c in completions if c["prompt_tokens"] > 2000],
        "requests_aborted": aborted,
        "prefill_rejected": text.count("prefill rejected"),
        "prefill_throttled": text.count("Prefill throttled"),
        "min_dynamic_ceiling_gb": min(ceilings) if ceilings else None,
    }


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

def force_thinking_off():
    original = model_settings.resolve_report_settings

    def resolved(model):
        s = dict(original(model))
        s["thinking"], s["thinking_source"] = False, "benchmark"
        return s

    model_settings.resolve_report_settings = resolved


def run_config(cfg, papers, interests, budget, omlx, original_settings, out_dir):
    log(f"\n{'=' * 70}\n[{cfg.name}] concurrency={cfg.concurrency} tier={cfg.tier} "
        f"cache={'on' if cfg.cache else 'off'} chunked_prefill={'on' if cfg.chunked_prefill else 'off'}\n{'=' * 70}")
    apply_settings(original_settings, cfg)
    restart_offset = log_size()
    omlx.restart(expect_tier=cfg.tier, serve_log=out_dir / f"omlx_serve_{cfg.name}.log")
    omlx.load_model()
    ssd_cache_logged = "paged SSD cache enabled" in read_log_since(restart_offset)
    if ssd_cache_logged != cfg.cache:
        log(f"  [!] cache={'on' if cfg.cache else 'off'} requested but oMLX "
            f"{'logged' if ssd_cache_logged else 'did not log'} 'paged SSD cache enabled'.")
    omlx.warm_up()

    # A per-config line ahead of the paper text keeps oMLX's prompt cache from reusing
    # the previous config's prefill of the same papers.
    nonce_interests = f"(benchmark run {cfg.name} {time.time():.0f})\n{interests}"
    reports_dir = out_dir / "reports" / cfg.name
    reports_dir.mkdir(parents=True, exist_ok=True)
    records = {}
    lock = threading.Lock()
    t0 = time.monotonic()

    def review_fn(paper, tag, on_first_token):
        rec = records.setdefault(paper["title"], {"title": paper["title"], "bucket": paper["bucket"],
                                                  "est_tokens": paper["est_tokens"], "attempts": 0})
        rec["attempts"] += 1
        rec["t_start"] = round(time.monotonic() - t0, 1)

        def first_token():
            rec["t_first"] = round(time.monotonic() - t0, 1)
            on_first_token()

        return agent.generate_paper_report(paper["title"], paper["url"], paper["paper_text"],
                                           nonce_interests, paper["access_info"], on_first_token=first_token)

    def on_done(paper, tag, report, error):
        with lock:
            rec = records[paper["title"]]
            rec["t_end"] = round(time.monotonic() - t0, 1)
            rec["status"] = "ok" if error is None else "failed"
            if error is not None:
                rec["error"] = str(error)[:300]
                log(f"{tag} [-] FAILED: {error}")
            else:
                safe = re.sub(r"[^A-Za-z0-9]+", "_", paper["title"])[:80]
                (reports_dir / f"{safe}.md").write_text(report, encoding="utf-8")
                log(f"{tag} [+] done at {rec['t_end']:.0f}s")

    log_offset = log_size()
    sampler = MemorySampler(omlx)
    sampler.start()
    try:
        sched = ReviewScheduler(review_fn, on_done, max_concurrency=cfg.concurrency, token_budget=budget)
        for p in sorted(papers, key=lambda p: -p["est_tokens"]):
            sched.submit(p, p["est_tokens"], label=p["title"][:30])
        sched.close()
        sched.run()
        abort_retries, peak = sched.abort_retries, sched.peak_concurrency
    finally:
        makespan = time.monotonic() - t0
        sampler.stop()

    server = parse_server_log(read_log_since(log_offset))

    paper_rows = sorted(records.values(), key=lambda r: r.get("t_end", 1e9))
    for row in paper_rows:
        if "t_first" in row:
            row["prefill_s"] = round(row["t_first"] - row["t_start"], 1)
            row["total_s"] = round(row["t_end"] - row["t_start"], 1)

    samples = [s for s in sampler.samples if s.get("footprint_gb")]
    peak_fp = max((s["footprint_gb"] for s in samples), default=None)
    ceilings = [s["ceiling_gb"] for s in sampler.samples if s.get("ceiling_gb")]
    min_ceiling = min(ceilings) if ceilings else server["min_dynamic_ceiling_gb"]
    spare = (round(min_ceiling * HARD_THRESHOLD[cfg.tier] - peak_fp, 2)
             if peak_fp is not None and min_ceiling else None)
    (out_dir / f"memory_{cfg.name}.json").write_text(json.dumps(sampler.samples), encoding="utf-8")

    return {
        "config": asdict(cfg),
        "token_budget": budget,
        "cooldown_seconds": config.REVIEW_COOLDOWN_SECONDS,
        "ssd_cache_logged": ssd_cache_logged,
        "makespan_s": round(makespan, 1),
        "papers_ok": sum(1 for r in records.values() if r.get("status") == "ok"),
        "papers_failed": sum(1 for r in records.values() if r.get("status") == "failed"),
        "abort_retries": abort_retries,
        "peak_concurrency": peak,
        "papers": paper_rows,
        "server": server,
        "memory": {
            "peak_footprint_gb": round(peak_fp, 2) if peak_fp is not None else None,
            "min_ceiling_gb": round(min_ceiling, 2) if min_ceiling else None,
            "abort_threshold_gb": round(min_ceiling * HARD_THRESHOLD[cfg.tier], 2) if min_ceiling else None,
            "spare_to_abort_at_peak_gb": spare,
            "max_swap_used_gb": round(max((s.get("swap_used_gb", 0) for s in sampler.samples), default=0), 2),
            "min_free_gb": round(min((s["free"] for s in sampler.samples if "free" in s), default=0), 2),
            "max_compressed_gb": round(max((s.get("compressed", 0) for s in sampler.samples), default=0), 2),
        },
    }


def write_summary(results, out_dir):
    base = next((r for r in results if r["config"]["name"] == "c1-balanced" and "skipped" not in r), None)
    lines = ["| Config | Makespan (min) | vs c1 | OK/lost | Retries | Server aborts | "
             "Throttles | Peak oMLX GB | Abort at GB | Spare GB | Max swap GB |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        if "skipped" in r:
            lines.append(f"| {r['config']['name']} | SKIPPED: {r['skipped'][:80]} |||||||||| |")
            continue
        m, s = r["memory"], r["server"]
        vs = (f"{(1 - r['makespan_s'] / base['makespan_s']) * 100:+.0f}% faster"
              if base and base is not r else "baseline" if base is r else "-")
        lines.append(
            f"| {r['config']['name']} | {r['makespan_s'] / 60:.1f} | {vs} | {r['papers_ok']}/{r['papers_failed']} | "
            f"{r['abort_retries']} | {s['requests_aborted']} | {s['prefill_throttled']} | {m['peak_footprint_gb']} | "
            f"{m['abort_threshold_gb']} | {m['spare_to_abort_at_peak_gb']} | {m['max_swap_used_gb']} |")
    lines += ["", "Est vs actual prompt tokens (paper order by completion):"]
    for r in (r for r in results if "skipped" not in r):
        ests = [p["est_tokens"] for p in r["papers"] if p.get("status") == "ok"]
        acts = [c["prompt_tokens"] for c in r["server"]["completions"]]
        lines.append(f"- {r['config']['name']}: est {ests} / actual {acts}")
    text = "\n".join(lines) + "\n"
    (out_dir / "summary.md").write_text(text, encoding="utf-8")
    return text


class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, s):
        for st in self.streams:
            st.write(s)
        return len(s)

    def flush(self):
        for st in self.streams:
            st.flush()


def cmd_run(args):
    if not CACHE_FILE.exists():
        sys.exit(f"No cached papers at {CACHE_FILE}; run `prepare` first.")
    if config.get_active_framework() != "omlx":
        sys.exit("LLM_FRAMEWORK is not omlx; the benchmark only drives oMLX.")
    papers = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    if args.papers:
        papers = sorted(papers, key=lambda p: p["est_tokens"])[:args.papers]
    interests = Path(config.INTERESTS_FILE).read_text(encoding="utf-8")
    configs = CONFIGS
    if args.configs:
        wanted = args.configs.split(",")
        configs = [c for c in CONFIGS if c.name in wanted]
        if len(configs) != len(wanted):
            sys.exit(f"Unknown config in {wanted}; choose from {[c.name for c in CONFIGS]}")

    out_dir = RESULTS_DIR / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    log_file = open(out_dir / "bench.log", "w", encoding="utf-8")
    sys.stdout = Tee(sys.__stdout__, log_file)
    sys.stderr = Tee(sys.__stderr__, log_file)

    force_thinking_off()
    omlx = OMLX()
    original_text = OMLX_SETTINGS.read_text(encoding="utf-8")
    original_settings = json.loads(original_text)
    (out_dir / "omlx_settings.backup.json").write_text(original_text, encoding="utf-8")
    was_up = omlx.is_up()
    was_loaded = was_up and omlx.model in ((omlx.status() or {}).get("loaded_models") or [])

    log(f"Benchmark: {len(papers)} papers, {len(configs)} config(s), token budget {args.budget}, "
        f"cool-down {config.REVIEW_COOLDOWN_SECONDS:.0f}s after reviews >= {config.REVIEW_COOLDOWN_TOKENS} tokens")
    log(f"Results: {out_dir}")
    for p in sorted(papers, key=lambda p: -p["est_tokens"]):
        log(f"  {p['bucket']:5} ~{p['est_tokens']:6} tokens  {p['title'][:70]}")
    log(f"Rough duration: {len(configs) * 20} min. Original oMLX settings backed up; they are "
        f"restored at the end, also on ctrl-C.")

    results = []
    try:
        for cfg in configs:
            try:
                results.append(run_config(cfg, papers, interests, args.budget, omlx, original_settings, out_dir))
            except (RuntimeError, requests.RequestException) as e:
                # Never time a config whose settings oMLX didn't confirm (2026-11-01 run).
                log(f"\n[!] {cfg.name} skipped: {e}")
                results.append({"config": asdict(cfg), "skipped": str(e)})
            (out_dir / "results.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
            log("\n" + write_summary(results, out_dir))
    except KeyboardInterrupt:
        log("\n[!] Interrupted; restoring oMLX settings.")
    except Exception as e:
        log(f"\n[!] Benchmark error: {e}; restoring oMLX settings.")
        raise
    finally:
        OMLX_SETTINGS.write_text(original_text, encoding="utf-8")
        log("Restored ~/.omlx/settings.json.")
        try:
            omlx.stop()
            if was_up:
                omlx.cli("start")
                omlx.wait_up()
                if was_loaded:
                    omlx.load_model()
        except Exception as e:
            log(f"[!] Could not return oMLX to its original state: {e}")
        if results:
            log("\n" + write_summary(results, out_dir))
        log(f"Done. Results in {out_dir}")


# ---------------------------------------------------------------------------
# probe (decision 0021)
# ---------------------------------------------------------------------------

# Cache on as in normal use; every probe request carries the app's header to skip storing.
PROBE_CFG = BenchConfig("probe", 0, "aggressive", True, False)


class Stream(threading.Thread):
    """
    One streamed review request with thinking on. Records when it was sent, when each
    token arrived and the server's usage. Setting stop_event closes the connection,
    which makes oMLX cancel the request.

    oMLX streams several tokens per chunk, and how many varies with load (smoke run
    2026-11-18: ~3 alone), so tokens are counted from the per-token logprobs entries
    each chunk carries, not from chunks.
    """

    def __init__(self, omlx, paper, interests, nonce, max_tokens, stop_event=None, temperature=1.0):
        super().__init__(daemon=True)
        self.omlx, self.paper, self.max_tokens = omlx, paper, max_tokens
        self.stop_event = stop_event or threading.Event()
        self.temperature = temperature
        # A unique line ahead of the paper text: no prompt reuse between requests.
        self.messages = agent.build_report_messages(
            paper["title"], paper["url"], paper["paper_text"],
            f"(probe {nonce} {time.time():.3f})\n{interests}", paper["access_info"])
        self.t_send = self.t_first = self.t_end = None
        self.token_times = []       # one entry per token (from logprobs)
        self.chunk_times = []       # one entry per text chunk (fallback if no logprobs)
        self.usage = None
        self.finish_reason = None
        self.error = None
        self.first_token = threading.Event()

    def run(self):
        body = {"model": self.omlx.model, "messages": self.messages, "temperature": self.temperature,
                "max_tokens": self.max_tokens, "stream": True,
                "stream_options": {"include_usage": True}, "enable_thinking": True,
                "logprobs": True, "top_logprobs": 0}
        self.t_send = time.monotonic()
        try:
            with requests.post(f"{self.omlx.v1}/chat/completions",
                               headers={**self.omlx.headers(), **config.OMLX_CACHE_STORE_HEADERS},
                               json=body, stream=True, timeout=(10, 3600)) as r:
                if not r.ok:
                    self.error = f"HTTP {r.status_code}: {r.text[:300]}"
                    return
                for raw in r.iter_lines():
                    if self.stop_event.is_set():
                        break
                    if not raw or not raw.startswith(b"data:"):
                        continue
                    data = raw[5:].strip()
                    if data == b"[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except ValueError:
                        continue
                    if chunk.get("error"):
                        self.error = str(chunk["error"])[:300]
                        break
                    if chunk.get("usage"):
                        self.usage = chunk["usage"]
                    for ch in chunk.get("choices") or []:
                        d = ch.get("delta") or {}
                        n = len((ch.get("logprobs") or {}).get("content") or [])
                        text = d.get("content") or d.get("reasoning_content") or d.get("reasoning")
                        if n or text:
                            now = time.monotonic()
                            if self.t_first is None:
                                self.t_first = now
                                self.first_token.set()
                            self.token_times.extend([now] * n)
                            if text:
                                self.chunk_times.append(now)
                        if ch.get("finish_reason"):
                            self.finish_reason = ch["finish_reason"]
        except requests.RequestException as e:
            self.error = str(e)[:300]
        finally:
            self.t_end = time.monotonic()
            if not self.token_times:
                self.token_times = list(self.chunk_times)
            if self.t_first is None and self.error is None and self.finish_reason:
                self.t_first = self.t_end       # max_tokens=1 can end without a text delta
            self.first_token.set()

    @property
    def ttft(self):
        return None if self.t_first is None else self.t_first - self.t_send


def tokens_in_window(token_times, start, end):
    """Tokens that arrived in [start, end]."""
    return sum(1 for t in token_times if start <= t <= end)


def aggregate_rate(streams_token_times, start, end):
    """Combined tokens/s of several streams over [start, end], and each stream's own rate."""
    span = end - start
    if span <= 0:
        return None, []
    each = [tokens_in_window(tt, start, end) / span for tt in streams_token_times]
    return sum(each), each


def release_time(samples, t_end, baseline_gb, tolerance_gb=1.0):
    """
    Seconds after t_end until oMLX's footprint first falls to baseline + tolerance,
    from samples carrying "mono" and "footprint_gb". None if it never does.
    """
    for s in sorted((s for s in samples if s.get("footprint_gb") is not None and "mono" in s),
                    key=lambda s: s["mono"]):
        if s["mono"] >= t_end and s["footprint_gb"] <= baseline_gb + tolerance_gb:
            return round(s["mono"] - t_end, 1)
    return None


def memory_summary(samples, tier=PROBE_CFG.tier):
    fps = [s["footprint_gb"] for s in samples if s.get("footprint_gb") is not None]
    ceilings = [s["ceiling_gb"] for s in samples if s.get("ceiling_gb")]
    peak = max(fps) if fps else None
    abort_at = min(ceilings) * HARD_THRESHOLD[tier] if ceilings else None
    return {
        "peak_footprint_gb": round(peak, 2) if peak is not None else None,
        "abort_threshold_gb": round(abort_at, 2) if abort_at else None,
        "spare_gb": round(abort_at - peak, 2) if peak is not None and abort_at else None,
        "max_swap_used_gb": round(max((s.get("swap_used_gb", 0) for s in samples), default=0), 2),
    }


def sampled(omlx, interval):
    sampler = MemorySampler(omlx, interval=interval)
    sampler.start()
    return sampler


def pick_pair(papers):
    """The two papers with the closest estimated length (stage A)."""
    ordered = sorted(papers, key=lambda p: p["est_tokens"])
    pairs = [(ordered[i + 1]["est_tokens"] - ordered[i]["est_tokens"], i) for i in range(len(ordered) - 1)]
    _, i = min(pairs)
    return ordered[i], ordered[i + 1]


def stage_a(omlx, papers, interests, temperature):
    """Two prompts one after the other vs at once; max_tokens=1, nothing else running."""
    a, b = pick_pair(papers)
    log(f"\n[A] Prompt processing: '{a['title'][:40]}' (~{a['est_tokens']}) and "
        f"'{b['title'][:40]}' (~{b['est_tokens']})")
    out = {"papers": [a["title"], b["title"]]}

    sampler = sampled(omlx, 2.0)
    serial = []
    for p in (a, b):
        s = Stream(omlx, p, interests, "A-serial", 1, temperature=temperature)
        s.start()
        s.join()
        serial.append(s)
        log(f"  serial: {p['title'][:40]} first token after {s.ttft or float('nan'):.1f}s"
            + (f" [error: {s.error}]" if s.error else ""))
    sampler.stop()
    out["serial"] = {"ttft_s": [round(s.ttft, 1) if s.ttft else None for s in serial],
                     "errors": [s.error for s in serial], "memory": memory_summary(sampler.samples)}

    time.sleep(10)
    sampler = sampled(omlx, 2.0)
    both = [Stream(omlx, p, interests, "A-concurrent", 1, temperature=temperature) for p in (a, b)]
    for s in both:
        s.start()
    for s in both:
        s.join()
    sampler.stop()
    firsts = [s.t_first for s in both if s.t_first]
    combined = (max(firsts) - min(s.t_send for s in both)) if len(firsts) == 2 else None
    out["concurrent"] = {"ttft_s": [round(s.ttft, 1) if s.ttft else None for s in both],
                         "both_done_s": round(combined, 1) if combined else None,
                         "errors": [s.error for s in both], "memory": memory_summary(sampler.samples)}
    serial_total = sum(s.ttft for s in serial) if all(s.ttft for s in serial) else None
    out["serial_total_s"] = round(serial_total, 1) if serial_total else None
    out["concurrent_vs_serial"] = round(combined / serial_total, 3) if combined and serial_total else None
    log(f"  concurrent: both first tokens after {combined or float('nan'):.1f}s vs "
        f"{serial_total or float('nan'):.1f}s one after the other "
        f"(ratio {out['concurrent_vs_serial']}; the prefill lock stays if >= 0.9)")
    return out


def stage_c(omlx, papers, interests, temperature, gap_s, max_tokens):
    """Memory release after a long review (C1), then a long prompt gap_s after one ends (C2)."""
    long_paper = max(papers, key=lambda p: p["est_tokens"])
    log(f"\n[C] Memory after a long review: '{long_paper['title'][:50]}' (~{long_paper['est_tokens']}), "
        f"output capped at {max_tokens} tokens")
    out = {"paper": long_paper["title"], "gap_s": gap_s}

    # C1: idle baseline, one long review to its natural end, then 60s of 1s samples.
    sampler = sampled(omlx, 1.0)
    time.sleep(8)
    s = Stream(omlx, long_paper, interests, "C1", max_tokens, temperature=temperature)
    s.start()
    s.join()
    time.sleep(60)
    sampler.stop()
    before = [x["footprint_gb"] for x in sampler.samples
              if x.get("footprint_gb") is not None and x.get("mono", 1e18) < s.t_send]
    baseline = min(before) if before else None
    curve = {}
    for offset in (0, 1, 2, 3, 5, 10, 20, 30, 60):
        pts = [x for x in sampler.samples if x.get("footprint_gb") is not None
               and x.get("mono", -1) >= s.t_end + offset]
        if pts:
            curve[f"+{offset}s"] = round(pts[0]["footprint_gb"], 2)
    counted = len(s.token_times)
    completion = (s.usage or {}).get("completion_tokens")
    out["c1"] = {
        "ttft_s": round(s.ttft, 1) if s.ttft else None,
        "finish_reason": s.finish_reason, "error": s.error,
        "completion_tokens": completion, "counted_tokens": counted, "chunks": len(s.chunk_times),
        # Should be 1.0: the stream's token count matches the server's usage.
        "usage_per_counted": round(completion / counted, 3) if completion and counted else None,
        "baseline_gb": round(baseline, 2) if baseline else None,
        "release_s": release_time(sampler.samples, s.t_end, baseline) if baseline else None,
        "curve_after_end_gb": curve,
        "memory": memory_summary(sampler.samples),
    }
    log(f"  C1: baseline {out['c1']['baseline_gb']} GB, peak {out['c1']['memory']['peak_footprint_gb']} GB, "
        f"back within 1 GB of baseline {out['c1']['release_s']}s after the review ended; curve {curve}")

    # C2: the same long review, then the same long prompt again gap_s after it ends.
    time.sleep(10)
    offset = log_size()
    sampler = sampled(omlx, 1.0)
    first = Stream(omlx, long_paper, interests, "C2-first", max_tokens, temperature=temperature)
    first.start()
    first.join()
    time.sleep(gap_s)
    second = Stream(omlx, long_paper, interests, "C2-second", 1, temperature=temperature)
    second.start()
    second.join()
    sampler.stop()
    server = parse_server_log(read_log_since(offset))
    during_second = [x for x in sampler.samples if x.get("mono", -1) >= second.t_send]
    out["c2"] = {
        "first_error": first.error, "second_error": second.error,
        "second_ttft_s": round(second.ttft, 1) if second.ttft else None,
        "server_aborts": server["requests_aborted"], "prefill_rejected": server["prefill_rejected"],
        "memory_during_second": memory_summary(during_second),
        "memory": memory_summary(sampler.samples),
    }
    ok = not second.error and not server["requests_aborted"] and not server["prefill_rejected"]
    log(f"  C2: second long prompt {gap_s}s after the first ended: {'OK' if ok else 'REJECTED'}; "
        f"peak during it {out['c2']['memory_during_second']['peak_footprint_gb']} GB, "
        f"spare {out['c2']['memory_during_second']['spare_gb']} GB")
    return out


def stage_b(omlx, papers, interests, temperature, ns, window_s):
    """Combined generation speed with 1..N reviews generating, prompts staggered like the app."""
    order = sorted(papers, key=lambda p: p["est_tokens"])     # shortest first: least prefill
    out = {"window_s": window_s, "runs": []}
    for n in ns:
        if n > len(order):
            log(f"\n[B] N={n}: only {len(order)} cached papers, skipped")
            continue
        log(f"\n[B] N={n}: staggered prompts, then {window_s}s with all {n} generating")
        time.sleep(10)
        offset = log_size()
        stop = threading.Event()
        sampler = sampled(omlx, 3.0)
        streams = []
        for i, p in enumerate(order[:n]):
            s = Stream(omlx, p, interests, f"B{n}-{i}", 32_768, stop_event=stop, temperature=temperature)
            s.start()
            s.first_token.wait()            # the app's prefill lock: one prompt at a time
            streams.append(s)
            log(f"  stream {i + 1}: '{p['title'][:40]}' first token after {s.ttft or float('nan'):.1f}s"
                + (f" [error: {s.error}]" if s.error else ""))
        errors = [s.error for s in streams if s.error]
        start = max((s.t_first for s in streams if s.t_first), default=time.monotonic())
        deadline = start + window_s
        while time.monotonic() < deadline and all(s.is_alive() for s in streams):
            time.sleep(0.5)
        end = min([time.monotonic()] + [s.t_end for s in streams if not s.is_alive() and s.t_end])
        stop.set()
        for s in streams:
            s.join(timeout=60)
        sampler.stop()
        total, each = aggregate_rate([s.token_times for s in streams], start, end)
        server = parse_server_log(read_log_since(offset))
        run = {
            "n": n, "window_s": round(end - start, 1),
            "aggregate_tok_s": round(total, 2) if total else None,
            "per_stream_tok_s": [round(x, 2) for x in each],
            "ttft_s": [round(s.ttft, 1) if s.ttft else None for s in streams],
            "errors": errors, "server_aborts": server["requests_aborted"],
            "prefill_rejected": server["prefill_rejected"],
            "memory": memory_summary(sampler.samples),
        }
        out["runs"].append(run)
        log(f"  N={n}: {run['aggregate_tok_s']} tok/s combined over {run['window_s']}s "
            f"({run['per_stream_tok_s']}), peak {run['memory']['peak_footprint_gb']} GB, "
            f"spare {run['memory']['spare_gb']} GB" + (f", errors {errors}" if errors else ""))
    prev = None
    for run in out["runs"]:
        if prev and prev["aggregate_tok_s"] and run["aggregate_tok_s"]:
            run["gain_vs_previous"] = round(run["aggregate_tok_s"] / prev["aggregate_tok_s"] - 1, 3)
        prev = run
    return out


def write_probe_summary(res, out_dir):
    lines = [f"# Probe {out_dir.name}", "",
             f"Model {res['model']}, tier {PROBE_CFG.tier}, cache on with X-oMLX-Cache-Store: off, thinking on.", ""]
    a = res.get("A")
    if a:
        lines += ["## A. Two prompts at once vs one after the other", "",
                  f"- One after the other: first tokens after {a['serial']['ttft_s']} s, total {a['serial_total_s']} s; "
                  f"peak {a['serial']['memory']['peak_footprint_gb']} GB",
                  f"- At once: first tokens after {a['concurrent']['ttft_s']} s, both done {a['concurrent']['both_done_s']} s; "
                  f"peak {a['concurrent']['memory']['peak_footprint_gb']} GB, spare {a['concurrent']['memory']['spare_gb']} GB",
                  f"- Ratio at once / one after the other: **{a['concurrent_vs_serial']}** "
                  f"(the prefill lock stays if >= 0.9)", ""]
    c = res.get("C")
    if c:
        c1, c2 = c["c1"], c["c2"]
        lines += ["## C. Memory after a long review", "",
                  f"- C1: baseline {c1['baseline_gb']} GB, peak {c1['memory']['peak_footprint_gb']} GB; back within "
                  f"1 GB of baseline **{c1['release_s']} s** after the end. Curve: {c1['curve_after_end_gb']}",
                  f"- Token count check: {c1['counted_tokens']} counted from the stream, "
                  f"{c1['completion_tokens']} by the server (ratio {c1['usage_per_counted']}, should be 1.0); "
                  f"{c1['chunks']} text chunks",
                  f"- C2: long prompt {c['gap_s']} s after a long review: errors {c2['second_error']}, "
                  f"server aborts {c2['server_aborts']}, prefill rejected {c2['prefill_rejected']}; peak during it "
                  f"{c2['memory_during_second']['peak_footprint_gb']} GB, spare {c2['memory_during_second']['spare_gb']} GB", ""]
    b = res.get("B")
    if b:
        lines += ["## B. Combined generation speed", "",
                  "| N | tok/s combined | gain vs N-1 | per stream | window s | peak GB | abort at GB | spare GB | swap GB | errors |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        for r in b["runs"]:
            m = r["memory"]
            gain = f"{r['gain_vs_previous'] * 100:+.0f}%" if r.get("gain_vs_previous") is not None else "-"
            lines.append(f"| {r['n']} | {r['aggregate_tok_s']} | {gain} | {r['per_stream_tok_s']} | {r['window_s']} | "
                         f"{m['peak_footprint_gb']} | {m['abort_threshold_gb']} | {m['spare_gb']} | "
                         f"{m['max_swap_used_gb']} | {len(r['errors']) + r['server_aborts'] + r['prefill_rejected']} |")
        lines += ["", "Adopt the largest N with gain >= 15% over N-1 and spare >= 6 GB (decision 0021)."]
    text = "\n".join(lines) + "\n"
    (out_dir / "probe.md").write_text(text, encoding="utf-8")
    return text


def restore_omlx(omlx, original_text, was_up, was_loaded):
    OMLX_SETTINGS.write_text(original_text, encoding="utf-8")
    log("Restored ~/.omlx/settings.json.")
    try:
        omlx.stop()
        if was_up:
            omlx.cli("start")
            omlx.wait_up()
            if was_loaded:
                omlx.load_model()
    except Exception as e:
        log(f"[!] Could not return oMLX to its original state: {e}")


def cmd_probe(args):
    if not CACHE_FILE.exists():
        sys.exit(f"No cached papers at {CACHE_FILE}; run `prepare` first.")
    if config.get_active_framework() != "omlx":
        sys.exit("LLM_FRAMEWORK is not omlx; the probe only drives oMLX.")
    papers = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    interests = Path(config.INTERESTS_FILE).read_text(encoding="utf-8")
    stages = [x.strip().upper() for x in args.stages.split(",")]
    ns = [int(x) for x in args.ns.split(",")]
    temperature = float(model_settings.resolve_report_settings(config.get_active_model())["temperature"])

    out_dir = RESULTS_DIR / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    log_file = open(out_dir / "bench.log", "w", encoding="utf-8")
    sys.stdout = Tee(sys.__stdout__, log_file)
    sys.stderr = Tee(sys.__stderr__, log_file)

    omlx = OMLX()
    original_text = OMLX_SETTINGS.read_text(encoding="utf-8")
    (out_dir / "omlx_settings.backup.json").write_text(original_text, encoding="utf-8")
    was_up = omlx.is_up()
    was_loaded = was_up and omlx.model in ((omlx.status() or {}).get("loaded_models") or [])
    log(f"Probe: stages {stages}, N {ns}, window {args.window}s, gap {args.gap}s, model {omlx.model}, "
        f"temperature {temperature}. Results: {out_dir}")

    res = {"model": omlx.model, "stages": stages}
    try:
        apply_settings(json.loads(original_text), PROBE_CFG)
        omlx.restart(expect_tier=PROBE_CFG.tier, serve_log=out_dir / "omlx_serve_probe.log")
        omlx.load_model()
        omlx.warm_up()
        if "A" in stages:
            res["A"] = stage_a(omlx, papers, interests, temperature)
            (out_dir / "probe.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
        if "C" in stages:
            res["C"] = stage_c(omlx, papers, interests, temperature, args.gap, args.c_max_tokens)
            (out_dir / "probe.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
        if "B" in stages:
            res["B"] = stage_b(omlx, papers, interests, temperature, ns, args.window)
            (out_dir / "probe.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    except KeyboardInterrupt:
        log("\n[!] Interrupted; restoring oMLX settings.")
    except Exception as e:
        log(f"\n[!] Probe error: {e}; restoring oMLX settings.")
        raise
    finally:
        (out_dir / "probe.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
        restore_omlx(omlx, original_text, was_up, was_loaded)
        log("\n" + write_probe_summary(res, out_dir))
        log(f"Done. Results in {out_dir}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare", help="pick and cache benchmark papers")
    p.add_argument("--force", action="store_true", help="pick papers again even if a cache exists")
    r = sub.add_parser("run", help="run the benchmark configurations")
    r.add_argument("--configs", help=f"comma-separated subset of: {','.join(c.name for c in CONFIGS)}")
    r.add_argument("--budget", type=int, default=config.REVIEW_TOKEN_BUDGET, help="review token budget")
    r.add_argument("--papers", type=int, help="use only the N shortest cached papers (smoke test)")
    q = sub.add_parser("probe", help="prompt overlap, generation scaling and memory release (thinking on)")
    q.add_argument("--stages", default="A,C,B", help="comma-separated subset of A,B,C (run in order A, C, B)")
    q.add_argument("--ns", default="1,2,3,4", help="stage B: reviews generating at once")
    q.add_argument("--window", type=float, default=180, help="stage B: seconds measured with all N generating")
    q.add_argument("--gap", type=float, default=5, help="stage C2: seconds between a long review and the next prompt")
    q.add_argument("--c-max-tokens", type=int, default=2000, help="stage C: output cap of the long review")
    args = ap.parse_args()
    {"prepare": cmd_prepare, "run": cmd_run, "probe": cmd_probe}[args.cmd](args)


if __name__ == "__main__":
    main()
