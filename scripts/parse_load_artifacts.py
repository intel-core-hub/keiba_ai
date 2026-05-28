import sys
import json
import glob
import os
import statistics

def extract_numbers(obj):
    nums = []
    if isinstance(obj, dict):
        for v in obj.values():
            nums += extract_numbers(v)
    elif isinstance(obj, list):
        for v in obj:
            nums += extract_numbers(v)
    elif isinstance(obj, (int, float)):
        nums.append(float(obj))
    return nums


def find_latency_list(d):
    # common keys
    for key in ("latencies", "durations", "durations_ms", "elapsed_ms", "times", "request_times", "response_times", "durations_ms"):
        if key in d and isinstance(d[key], list):
            return extract_numbers(d[key])
    # some formats embed per-request dicts under "requests" or "samples"
    for key in ("requests","samples","results"):
        if key in d and isinstance(d[key], list):
            numbers = []
            for item in d[key]:
                if isinstance(item, dict):
                    for cand in ("latency_ms","elapsed_ms","duration_ms","latency","duration","time_ms","elapsed"): 
                        if cand in item:
                            numbers.append(float(item[cand]))
                    # fallback: extract any numeric values inside
                    if not numbers:
                        numbers += extract_numbers(item)
            if numbers:
                return numbers
    # last resort: extract any numeric values from top-level
    all_nums = extract_numbers(d)
    return all_nums


def safe_percentiles(arr, ps=(50,95,99)):
    if not arr:
        return {p: None for p in ps}
    arr = sorted(arr)
    n = len(arr)
    res = {}
    for p in ps:
        # use nearest-rank method
        k = int(round((p/100.0)*(n-1)))
        res[p] = arr[k]
    return res


def analyze_file(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            d = json.load(f)
    except Exception as e:
        return (path, str(e), None)
    lat = find_latency_list(d)
    if not lat:
        return (path, 'no-latency-data-found', None)
    # try statistics.quantiles when enough data
    try:
        if len(lat) >= 3:
            qs = statistics.quantiles(lat, n=100)
            p50 = qs[49]
            p95 = qs[94]
            p99 = qs[98]
        else:
            vals = safe_percentiles(lat)
            p50 = vals[50]
            p95 = vals[95]
            p99 = vals[99]
    except Exception:
        vals = safe_percentiles(lat)
        p50 = vals[50]
        p95 = vals[95]
        p99 = vals[99]
    return (path, 'ok', {'count': len(lat), 'p50': p50, 'p95': p95, 'p99': p99})


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else 'gh_artifacts'
    patterns = [os.path.join(base, '**', 'load_test_*.json'), os.path.join(base, '**', '*.json')]
    seen = set()
    files = []
    for pat in patterns:
        for f in glob.glob(pat, recursive=True):
            if f not in seen:
                files.append(f)
                seen.add(f)
    if not files:
        print('NO_JSON_ARTIFACTS_FOUND')
        return 2
    results = []
    for f in files:
        res = analyze_file(f)
        results.append(res)
    for path, status, data in results:
        if status != 'ok':
            print(f'FILE: {path} STATUS: {status}')
        else:
            print(f'FILE: {path} COUNT: {data["count"]} P50: {data["p50"]} P95: {data["p95"]} P99: {data["p99"]}')
    return 0

if __name__ == '__main__':
    sys.exit(main())
