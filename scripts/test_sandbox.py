"""
KaryaSetu AI — Sandbox Isolation CLI Tester
Runs containment probes and agent tasks against the sandbox engine.

Usage:
    python scripts/test_sandbox.py
"""
import sys
import json
import time

try:
    import urllib.request
    import urllib.error
except ImportError:
    pass

API_BASE = "http://127.0.0.1:8001/api/v1/sandbox"

def print_header(title: str):
    print("\n" + "=" * 65)
    print(f"  {title}")
    print("=" * 65)

def http_get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "KaryaSetu-CLI"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))

def http_post(url: str, data: dict = None):
    payload = json.dumps(data or {}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "KaryaSetu-CLI"}
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))

def main():
    print_header("KaryaSetu AI — Agent Sandbox Verification CLI")
    print("Connecting to backend at: http://127.0.0.1:8001 ...")

    # 1. Status Check
    try:
        status = http_get(f"{API_BASE}/status")
    except Exception as exc:
        print(f"\n[FAIL] Could not connect to backend: {exc}")
        print("Please ensure the FastAPI backend is running on port 8001.")
        sys.exit(1)

    print("\n[+] 1. Sandbox Engine Status:")
    print(f"    - Docker Available    : {'YES' if status['docker_available'] else 'NO (Resilient Fallback Active)'}")
    print(f"    - Default Mode        : {status['default_mode'].upper()}")
    print("    - Active Security Controls:")
    for feature in status.get("isolation_features", []):
        print(f"      * {feature}")

    # 2. Security Containment Probe
    print("\n[+] 2. Executing Zero-Trust Containment Probe ...")
    try:
        probe = http_post(f"{API_BASE}/probe")
        print(f"    - Task ID             : {probe.get('task_id')}")
        print(f"    - Execution Status    : {probe.get('status').upper()}")
        print(f"    - Mode                : {probe.get('execution_mode')}")
        print(f"    - Duration            : {probe.get('duration_ms', 0):.2f} ms")
        
        output = probe.get("output", {})
        print("    - Probe Verification Signals:")
        print(f"      * Root Read-Only    : {output.get('root_filesystem_read_only')}")
        print(f"      * Air-Gapped Network: {output.get('air_gapped_network')}")
        print(f"      * Non-Root User UID : {output.get('non_root_uid')}")
        print(f"      * Message           : {output.get('message')}")
    except Exception as exc:
        print(f"    [FAIL] Probe error: {exc}")

    # 3. Agent Execution Test
    print("\n[+] 3. Executing Sandboxed Document Parse Agent Task ...")
    test_task = {
        "task_id": "test-parse-001",
        "task_type": "parse",
        "payload": {
            "content": "KaryaSetu Policy Brief: Classification RESTRICTED. Model routing: Local Gemma-3."
        },
        "timeout_seconds": 30
    }
    try:
        agent_res = http_post(f"{API_BASE}/execute", test_task)
        print(f"    - Task ID             : {agent_res.get('task_id')}")
        print(f"    - Execution Status    : {agent_res.get('status').upper()}")
        print(f"    - Chars Parsed        : {agent_res.get('output', {}).get('chars_parsed')}")
        print(f"    - Sanitized           : {agent_res.get('output', {}).get('sanitized')}")
        print(f"    - Latency             : {agent_res.get('duration_ms', 0):.2f} ms")
    except Exception as exc:
        print(f"    [FAIL] Agent execution error: {exc}")

    # 4. Sandboxed Transformation Generator Agent Test
    print("\n[+] 4. Executing Sandboxed Transformation Agent (Executive Summary Generator) ...")
    generator_task = {
        "task_id": "test-summary-001",
        "task_type": "summary_agent",
        "payload": {
            "output_format": "summary",
            "instruction": "Generate executive briefing with claim provenance"
        },
        "timeout_seconds": 30
    }
    try:
        gen_res = http_post(f"{API_BASE}/execute", generator_task)
        print(f"    - Task ID             : {gen_res.get('task_id')}")
        print(f"    - Execution Status    : {gen_res.get('status').upper()}")
        print(f"    - Agent               : {gen_res.get('output', {}).get('agent')}")
        print(f"    - Grounding Verified  : {gen_res.get('output', {}).get('grounding_verified')}")
        print(f"    - Latency             : {gen_res.get('duration_ms', 0):.2f} ms")
    except Exception as exc:
        print(f"    [FAIL] Generator execution error: {exc}")

    print_header("ALL SANDBOX CHECKS COMPLETED")

if __name__ == "__main__":
    main()
