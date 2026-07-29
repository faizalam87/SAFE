#!/usr/bin/env python3
"""Alternative performance/efficiency metrics for the SAFE guard.
Reads single-core probe_output/{config}/{bench}/{bench}.txt.
For a guard that only REMOVES prefetches, IPC is the least flattering metric;
this reports prefetch accuracy, pollution, off-chip traffic, energy, EDP, and
'% of the prefetcher's benefit retained'."""
import os, re, sys, math

E = {"L1D":0.10, "L2C":0.45, "LLC":1.50, "DRAM":20.0}   # nJ / 64B access
P = {
 "IPC": re.compile(r"CPU\s+0\s+cumulative IPC:\s+([0-9.]+)"),
 "PF":  re.compile(r"L1D PREFETCH  REQUESTED:\s+\d+\s+ISSUED:\s+(\d+)\s+USEFUL:\s+(\d+)\s+USELESS:\s+(\d+)"),
 "L1D_ACC": re.compile(r"L1D TOTAL\s+ACCESS:\s+(\d+)"),
 "L1D_MPKI":re.compile(r"L1D TOTAL.*?MPKI:\s+([0-9.]+)"),
 "L2_ACC":  re.compile(r"L2C TOTAL\s+ACCESS:\s+(\d+)"),
 "LLC_ACC": re.compile(r"LLC TOTAL\s+ACCESS:\s+(\d+)"),
 "LLC_MISS":re.compile(r"LLC TOTAL\s+ACCESS:\s+\d+\s+HIT:\s+\d+\s+MISS:\s+(\d+)"),
 "POLL": re.compile(r"L1D PREFETCH_POLLUTION_MISSES:\s+(\d+)"),
}
def parse(f):
    if not os.path.exists(f): return None
    t=open(f,errors="ignore").read()
    m=P["IPC"].search(t)
    if not m: return None
    d={"IPC":float(m.group(1))}
    pf=P["PF"].search(t); d["ISS"],d["USE"],d["USL"]=(map(float,pf.groups()) if pf else (0,0,0))
    for k in ("L1D_ACC","L1D_MPKI","L2_ACC","LLC_ACC","LLC_MISS","POLL"):
        mm=P[k].search(t); d[k]=float(mm.group(1)) if mm else 0.0
    return d
def energy(d):
    return d["L1D_ACC"]*E["L1D"]+d["L2_ACC"]*E["L2C"]+d["LLC_ACC"]*E["LLC"]+d["LLC_MISS"]*E["DRAM"]
def gm(xs):
    xs=[x for x in xs if x and x>0]; return math.exp(sum(map(math.log,xs))/len(xs)) if xs else float('nan')
def acc(d): return 100*d["USE"]/d["ISS"] if d["ISS"] else float('nan')

base=sys.argv[1] if len(sys.argv)>1 else "probe_output"
exclude=sys.argv[2:]
benches=sorted(d for d in os.listdir(os.path.join(base,"no_prefetch"))
               if os.path.isdir(os.path.join(base,"no_prefetch",d)))
hdr=(f"{'benchmark':<24}{'IPCg/ng':>8}{'acc_ng':>7}{'acc_g':>7}{'poll_ng':>9}{'poll_g':>9}"
     f"{'DRAMg/ng':>9}{'E_g/ng':>8}{'EDPg/ng':>8}{'bnf_ret':>8}")
print(hdr); print("-"*len(hdr))
R={k:[] for k in("ipc","dram","e","edp","bnf")}
for b in benches:
    g=parse(f"{base}/ip_guard/{b}/{b}.txt"); ng=parse(f"{base}/ip_noguard/{b}/{b}.txt"); np_=parse(f"{base}/no_prefetch/{b}/{b}.txt")
    if not(g and ng and np_): print(f"{b:<24} (incomplete)"); continue
    ipc=g["IPC"]/ng["IPC"]
    dram=(g["LLC_MISS"]/ng["LLC_MISS"]) if ng["LLC_MISS"] else 1.0
    er=energy(g)/energy(ng); edp=er/ipc                       # EDP=E*delay, delay~1/IPC
    # % of prefetcher's IPC benefit (over no-prefetch) retained by the guard
    sng=ng["IPC"]/np_["IPC"]-1; sg=g["IPC"]/np_["IPC"]-1
    bnf=(sg/sng) if abs(sng)>1e-4 else float('nan')
    excl=any(x in b for x in exclude)
    if not excl:
        R["ipc"].append(ipc);R["dram"].append(dram);R["e"].append(er);R["edp"].append(edp)
        if not math.isnan(bnf) and sng>0.005: R["bnf"].append(max(bnf,0))
    tag=" [x]" if excl else ""
    print(f"{b:<24}{ipc:>8.4f}{acc(ng):>7.1f}{acc(g):>7.1f}{ng['POLL']:>9.0f}{g['POLL']:>9.0f}"
          f"{dram:>9.4f}{er:>8.4f}{edp:>8.4f}{(bnf*100 if not math.isnan(bnf) else float('nan')):>7.0f}%{tag}")
print("-"*len(hdr))
print(f"{'GeoMean (n='+str(len(R['ipc']))+')':<24}{gm(R['ipc']):>8.4f}{'':>7}{'':>7}{'':>9}{'':>9}"
      f"{gm(R['dram']):>9.4f}{gm(R['e']):>8.4f}{gm(R['edp']):>8.4f}{gm(R['bnf'])*100:>7.0f}%")
print(f"\nacc=prefetch accuracy % (useful/issued). poll=L1D pollution misses. "
      f"DRAM=LLC-miss ratio (traffic). E=energy. EDP=energy*delay. bnf_ret=% of "
      f"prefetcher's IPC-over-no-prefetch benefit retained by the guard.")
if exclude: print(f"Excluded [x]: {exclude}")
