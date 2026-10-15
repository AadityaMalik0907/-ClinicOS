"""Small, reproducible authenticated patient-list load check for ClinicOS.

Use only against a development/staging deployment with synthetic data. Each GET
to the patient list is audit logged, so this tool requires explicit opt-in.
"""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from http.cookiejar import CookieJar
import getpass
import json
import os
import statistics
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.parse import urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen


def request_json(opener, url, *, method="GET", payload=None, csrf=None):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if csrf:
        headers["X-CSRFToken"] = csrf
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with opener.open(request, timeout=30) as response:
            content = response.read()
            return response.status, json.loads(content) if content else {}
    except HTTPError as error:
        return error.code, error.read().decode("utf-8", errors="replace")[:500]


def percentile(sorted_values, fraction):
    if not sorted_values:
        return None
    index = (len(sorted_values) - 1) * fraction
    low = int(index)
    high = min(low + 1, len(sorted_values) - 1)
    return round(sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (index - low), 2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="ClinicOS origin, e.g. http://127.0.0.1:8000")
    parser.add_argument("--organization-id", required=True, type=int)
    parser.add_argument("--requests", type=int, default=100, dest="request_count")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--allow-audit-writes", action="store_true",
        help="Confirm that each patient-list GET appends an audit event.",
    )
    args = parser.parse_args()
    if not args.allow_audit_writes:
        parser.error("patient-list requests are audit logged; pass --allow-audit-writes to proceed")
    if args.organization_id < 1 or not 1 <= args.request_count <= 10000 or not 1 <= args.workers <= 100:
        parser.error("organization-id must be positive; requests must be 1..10000 and workers 1..100")

    parsed_url = urlsplit(args.base_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc or parsed_url.username or parsed_url.password or parsed_url.query or parsed_url.fragment:
        parser.error("base-url must be an http(s) origin without embedded credentials, query, or fragment")
    base_url = args.base_url.rstrip("/")
    cookie_jar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(cookie_jar))
    email = os.environ.get("CLINICOS_BENCH_EMAIL") or input("ClinicOS email: ").strip()
    password = os.environ.get("CLINICOS_BENCH_PASSWORD") or getpass.getpass("ClinicOS password: ")

    status_code, _ = request_json(opener, base_url + "/api/v1/auth/csrf/")
    if status_code != 200:
        raise SystemExit(f"Could not obtain CSRF cookie (HTTP {status_code}).")
    csrf_cookie = next((cookie.value for cookie in cookie_jar if cookie.name == "csrftoken"), None)
    if not csrf_cookie:
        raise SystemExit("Server did not set a CSRF cookie.")
    status_code, _ = request_json(
        opener, base_url + "/api/v1/auth/login/", method="POST",
        payload={"email": email, "password": password}, csrf=csrf_cookie,
    )
    if status_code != 200:
        raise SystemExit(f"Login failed (HTTP {status_code}); credentials were not printed.")

    # Django rotates the CSRF token at login. Fetch the new cookie before PUT.
    status_code, _ = request_json(opener, base_url + "/api/v1/auth/csrf/")
    csrf_cookie = next((cookie.value for cookie in cookie_jar if cookie.name == "csrftoken"), None)
    if status_code != 200 or not csrf_cookie:
        raise SystemExit("Could not refresh CSRF cookie after login.")
    status_code, _ = request_json(
        opener, base_url + "/api/v1/organizations/selection/", method="PUT",
        payload={"organization_id": args.organization_id}, csrf=csrf_cookie,
    )
    if status_code != 200:
        raise SystemExit(f"Could not select organization (HTTP {status_code}); verify membership and role.")

    # Freeze authenticated cookies so concurrent requests don't mutate a shared jar.
    cookie_header = "; ".join(f"{cookie.name}={cookie.value}" for cookie in cookie_jar)
    target_url = base_url + "/api/v1/patients/?" + urlencode({"page_size": 50})

    def one_request(_):
        request = Request(target_url, headers={"Accept": "application/json", "Cookie": cookie_header})
        started = time.perf_counter()
        try:
            with urlopen(request, timeout=30) as response:
                response.read()
                return response.status, (time.perf_counter() - started) * 1000
        except HTTPError as error:
            error.read()
            return error.code, (time.perf_counter() - started) * 1000
        except (URLError, TimeoutError, OSError):
            return "network_error", (time.perf_counter() - started) * 1000

    elapsed_start = time.perf_counter()
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(one_request, i) for i in range(args.request_count)]
        for future in as_completed(futures):
            results.append(future.result())
    elapsed = time.perf_counter() - elapsed_start
    latencies = sorted(latency for _, latency in results)
    statuses = Counter(str(code) for code, _ in results)
    report = {
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "organization_id": args.organization_id,
        "endpoint": "/api/v1/patients/?page_size=50",
        "request_count": args.request_count,
        "workers": args.workers,
        "elapsed_seconds": round(elapsed, 3),
        "requests_per_second": round(args.request_count / elapsed, 2) if elapsed else None,
        "latency_ms": {
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "p99": percentile(latencies, 0.99),
            "mean": round(statistics.fmean(latencies), 2) if latencies else None,
        },
        "status_counts": dict(statuses),
        "note": "Patient-list reads append audit events; response bodies and credentials are not reported.",
    }
    print(json.dumps(report, indent=2))
    if any(code != 200 for code, _ in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
