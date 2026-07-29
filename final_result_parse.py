import os
import re
import csv
import math

BASE_DIR = "temp_output"
CONFIGS = ["no_prefetch", "ip_noguard", "ip_guard"]

# =====================================================================
# GENERIC METRIC REGISTRY
# Add any new metric here. {0} is a placeholder for the CPU index (0-3).
# =====================================================================
METRICS_MAP = {
    "IPC":              r"CPU\s+({0})\s+cumulative IPC:\s+([0-9.]+)",
#    "Cycles":           r"CPU\s+({0})\s+cycles:\s+(\d+)",
#    "Requested":        r"CPU\s+({0}).*?L1D.*?REQUESTED:\s+(\d+)",
#    "Issued":           r"CPU\s+({0}).*?L1D.*?ISSUED:\s+(\d+)",
#    "Useful":           r"CPU\s+({0}).*?L1D.*?USEFUL:\s+(\d+)",
#    "Useless":          r"CPU\s+({0}).*?L1D.*?USELESS:\s+(\d+)",
#    "Accuracy":         r"CPU\s+({0}).*?L1D.*?ACCURACY:\s+([0-9.]+)",
#    "Timely_PF":        r"CPU\s+({0}).*?L1D.*?TIMELY PREFETCHES:\s+(\d+)",
#    "Late_PF":          r"CPU\s+({0}).*?L1D.*?LATE PREFETCHES:\s+(\d+)",
#    "Dropped_PF":       r"CPU\s+({0}).*?L1D.*?DROPPED PREFETCHES:\s+(\d+)",
#    "Pollution_Misses": r"CPU\s+({0}).*?L1D.*?PREFETCH_POLLUTION_MISSES:\s+(\d+)",
#    "PF_Evictions":     r"CPU\s+({0}).*?L1D.*?PF_EVICTIONS_OF_USEFUL_LINES:\s+(\d+)",
#    "Net_Benefit":      r"CPU\s+({0}).*?L1D.*?NET_PREFETCH_BENEFIT:\s+(-?\d+)",
#    "PF_Killed":        r"CPU\s+({0}).*?L1D.*?PF_KILLED_BY_HEAP_GUARD:\s+(\d+)",
}

# CHOOSE YOUR METRIC HERE
TARGET_METRIC = "IPC" 

# =====================================================================

def get_compiled_patterns(metric_name):
    """Generates a list of 4 regex objects, one for each core."""
    raw_pattern = METRICS_MAP.get(metric_name)
    if not raw_pattern:
        raise ValueError(f"Metric '{metric_name}' not found in METRICS_MAP")
    return [re.compile(raw_pattern.format(i)) for i in range(4)]

def geomean(iterable):
    """Calculates Geometric Mean, ignoring N/A and zero/negative values."""
    values = []
    for x in iterable:
        try:
            val = float(x)
            if val > 0: values.append(val)
        except (ValueError, TypeError): continue
    if not values: return "N/A"
    return math.exp(sum(math.log(x) for x in values) / len(values))

def extract_metrics(file_path, patterns):
    """Extracts the chosen metric for all 4 cores from a file."""
    results = {str(i): "N/A" for i in range(4)}
    if not os.path.exists(file_path): return results
    
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            found_mask = [False] * 4
            for line in f:
                for i, pat in enumerate(patterns):
                    if not found_mask[i]:
                        match = pat.search(line)
                        if match:
                            results[str(i)] = match.group(2) # Group 2 is the value
                            found_mask[i] = True
                if all(found_mask): break
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
    return results

def main():
    patterns = get_compiled_patterns(TARGET_METRIC)
    
    try:
        bench_dir = os.path.join(BASE_DIR, CONFIGS[0])
        benchmarks = sorted([d for d in os.listdir(bench_dir) if os.path.isdir(os.path.join(bench_dir, d))])
    except FileNotFoundError:
        print(f"Directory error: Check BASE_DIR and CONFIGS paths.")
        return

    table_data = []
    for bench in benchmarks:
        row = {"Benchmark": bench}
        for config in CONFIGS:
            file_path = os.path.join(BASE_DIR, config, bench, f"{bench}.txt")
            data = extract_metrics(file_path, patterns)
            
            # Store per-core data and calc geomean
            for cpu_id, val in data.items():
                row[f"{config}_CPU{cpu_id}"] = val
            g = geomean(data.values())
            row[f"{config}_GeoMean"] = round(g, 4) if isinstance(g, float) else g
            
        table_data.append(row)

    # Prepare CSV columns
    core_cols = []
    for cfg in CONFIGS:
        core_cols.extend([f"{cfg}_CPU{i}" for i in range(4)] + [f"{cfg}_GeoMean"])

    output_file = f"Results_{TARGET_METRIC}.csv"
    with open(output_file, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=["Benchmark"] + core_cols)
        writer.writeheader()
        writer.writerows(table_data)

    # Print Summary Table
    print(f"\nMetric: {TARGET_METRIC}")
    header = f"{'Benchmark':<20} | " + " | ".join([f"{c[:12]:<12}" for c in CONFIGS])
    print(header + "\n" + "-" * len(header))
    for r in table_data:
        vals = [str(r[f"{c}_GeoMean"]) for c in CONFIGS]
        print(f"{r['Benchmark']:<20} | " + " | ".join([f"{v:<12}" for v in vals]))

if __name__ == "__main__":
    main()