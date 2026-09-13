"""Try importing test/script files (which may not be in packages)."""
from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

EXCLUDE_DIRS = {".venv", "__pycache__", "node_modules", ".git", ".pytest_cache"}

# Test/script files to check (those not imported by main modules)
test_files = [
    "_check_and_start_flare.py",
    "_deploy_flaresolverr.py",
    "_fix_proxy.py",
    "_full_test.py",
    "_ssh_check.py",
    "_test_auth.py",
    "_test_chatgpt.py",
    "_test_chatgpt_detail.py",
    "_test_public.py",
    "ssh_check_env.py",
    "ssh_complete_start.py",
    "ssh_debug_grok.py",
    "scripts/batch_test_http_proxies.py",
    "scripts/update_proxy_config.py",
    "tests/_test_flare_debug.py",
    "tests/test_browser_runner.py",
    "tests/test_chatgpt_register.py",
    "tests/test_clash_proxy.py",
    "tests/test_flaresolverr.py",
    "tests/test_flaresolverr_noproxy.py",
    "tests/test_mailnest.py",
    "tests/test_proxy_detail.py",
    "tests/test_xunmail.py",
    "web/app.py",
    "projects/nvidia_build/_test_l1_http.py",
    "projects/nvidia_build/_test_l2_http.py",
    "projects/nvidia_build/capture_api_endpoints.py",
    "projects/nvidia_build/capture_network.py",
    "projects/nvidia_build/capture_register_api.py",
    "projects/nvidia_build/capture_register_api_v3.py",
    "projects/nvidia_build/check_validation_api.py",
    "projects/nvidia_build/find_api.py",
    "projects/nvidia_build/intercept_register.py",
    "projects/nvidia_build/search_js_api.py",
    "projects/nvidia_build/search_js_api2.py",
    "projects/nvidia_build/test_api_endpoints.py",
    "projects/nvidia_build/test_browser_capture.py",
    "projects/nvidia_build/test_captcharun_cf.py",
    "projects/nvidia_build/test_flaresolverr.py",
    "projects/nvidia_build/test_http_register.py",
    "projects/nvidia_build/test_http_register_full.py",
    "projects/nvidia_build/test_http_simple.py",
    "projects/nvidia_build/test_http_v2.py",
    "projects/nvidia_build/test_hybrid_full.py",
    "projects/nvidia_build/test_hybrid_mode.py",
    "projects/nvidia_build/test_hybrid_v3.py",
    "projects/nvidia_build/test_hybrid_v4.py",
    "projects/nvidia_build/test_hybrid_v5.py",
    "projects/nvidia_build/test_hybrid_v6.py",
    "projects/nvidia_build/test_hybrid_v7.py",
    "projects/nvidia_build/test_l1_hybrid.py",
    "projects/nvidia_build/test_otp_endpoints.py",
    "projects/nvidia_build/test_otp_extended.py",
    "projects/nvidia_build/test_patchright_cf.py",
    "projects/nvidia_build/test_register_fields.py",
    "projects/nvidia_build/test_verify_page.py",
    "projects/nvidia_build/extract_urls.py",
]

fail = 0
ok = 0
skip = 0
for f in test_files:
    p = ROOT / f
    if not p.exists():
        print(f"SKIP {f} (file not found)")
        skip += 1
        continue
    # Convert file path to dotted module name
    rel = p.relative_to(ROOT)
    parts = list(rel.parts)
    mod_name = parts[-1][:-3]  # strip .py
    # Build dotted path using directory parts - but only if dirs have __init__.py
    cur = ROOT
    pkg_parts = []
    for part in parts[:-1]:
        cur = cur / part
        if (cur / "__init__.py").exists():
            pkg_parts.append(part)
        else:
            # Not a package; can't import as module. Use load_source instead.
            pkg_parts = None
            break
    try:
        if pkg_parts is not None:
            full = ".".join(pkg_parts + [mod_name])
            importlib.import_module(full)
            print(f"OK   {f}")
            ok += 1
        else:
            # load via importlib.util
            spec = importlib.util.spec_from_file_location(mod_name + "_tmp", p)
            if spec is None or spec.loader is None:
                print(f"SKIP {f} (no spec)")
                skip += 1
                continue
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            print(f"OK   {f}")
            ok += 1
    except Exception as e:
        print(f"FAIL {f}: {type(e).__name__}: {e}")
        fail += 1

print(f"--- {ok} OK / {fail} FAIL / {skip} SKIP ---")
