#!/usr/bin/env python3
"""
LineDensityCleanUp for DXF  (v2)

Removes duplicate, near-parallel and leftover fragment lines from a DXF *before* it goes into
Illustrator. Same detection logic and the same distances as the Illustrator script
LineDensityCleanUp v5 (Illustrator/LineDensityCleanUp_v5.jsx).

The input DXF is never changed. For each input file it writes:
    <name>_clean.dxf    the drawing without the removed lines (import this into Illustrator)
    <name>_review.dxf   everything; removed lines moved to colored layers LDC_Duplicates,
                        LDC_Near-parallel, LDC_Fragments (and LDC_Stubs) so you can check them;
                        gap bridges on LDC_Bridges
v2: closes small gaps where a kept line stops just short of another kept line, both gaps the
    cleanup created (by removing a connecting line) and gaps already in the export. Each gap gets
    a short straight bridge line. --no-bridge gives the v1 result.

Distances in SETTINGS are in points at the figure's FINAL printed size, exactly as in the
Illustrator script. Tell the script the final size with --width (e.g. 4in, 100mm, 288pt) or give
the scale directly with --scale (points per drawing unit). Without either, it asks.

Usage:
    python LineDensityCleanUp_dxf.py drawing.dxf --width 4in
    python LineDensityCleanUp_dxf.py *.dxf --width 6.5in --layers Visible,0
Requires: Python 3.8+ and ezdxf  (pip install ezdxf)
"""

import math
import os
import sys
import time

# ---------------- SETTINGS (distances in points at final size; same as the Illustrator script) ----------------
SETTINGS = {
    "removeDuplicates": True,    # exact copies stacked on top of each other
    "dupDecimals": 3,            # two lines count as copies if they match to 0.001 pt

    "removeNearParallel": True,  # lines running alongside a kept line
    "nearDist": 0.40,            # "alongside" = within this distance (pt). Lower = removes less
    "angleTolDeg": 12,           # and within this angle
    "nearCoverage": 0.90,        # and for at least this share of its length

    "useChains": True,           # treat touching pieces of one continuous line as one line
    "joinTol": 0.01,
    "maxTurnDeg": 20,
    "dirBack": 0.15,

    "removeOrphans": True,       # short leftovers whose connection was removed
    "orphanMaxLength": 0.30,
    "touchTol": 0.02,

    "removeStubs": False, "stubMaxLength": 0.6, "stubDist": 0.15, "stubCoverage": 0.9,
    "flattenStep": 0.05,
    "sampleStep": 0.05,

    # v2: close small gaps where a kept line stops just short of another kept line
    "bridgeGaps": True,
    "gapMax": 0.5,               # largest gap to close (pt)
    "bridgeMaxAngleDeg": 60,     # a bridge must leave the line end within this angle of the line's own direction
    "bridgeAnyAngleBelow": 0.05, # gaps shorter than this (pt) are closed in any direction
}
# -----------------------------------------------------------------------------------------------------------------

# =====================================================================================================
# Core: a line-for-line port of the LineDensityCleanUp core (v3) from the Illustrator script.
# Input:  paths = [{"closed": bool, "pp": [ax,ay,lx,ly,rx,ry, ...] (flat, 6 per point), "locked": bool}]
#         (locked = context only: compared against, never removed)
# Output: list of verdicts, same order: "keep" | "dup" | "near" | "stub" | "orphan"
# Floating-point operations are written in the same order as the JavaScript so the results match.
# =====================================================================================================

_sqrt = math.sqrt
_floor = math.floor


def ldc_dist(ax, ay, bx, by):
    dx = bx - ax
    dy = by - ay
    return _sqrt(dx * dx + dy * dy)


def js_round(x):
    """JavaScript Math.round: halves round up (toward +infinity)."""
    r = _floor(x)
    return r + 1 if x - r >= 0.5 else r


def js_ceil(x):
    return int(math.ceil(x))


def ldc_flatten(pp, closed, step):
    out = []
    n = len(pp) // 6
    if n == 0:
        return out
    segs = n if closed else n - 1
    out.append(pp[0]); out.append(pp[1])
    for i in range(segs):
        a = i * 6
        b = ((i + 1) % n) * 6
        x0 = pp[a]; y0 = pp[a + 1]; x1 = pp[a + 4]; y1 = pp[a + 5]
        x2 = pp[b + 2]; y2 = pp[b + 3]; x3 = pp[b]; y3 = pp[b + 1]
        if x1 == x0 and y1 == y0 and x2 == x3 and y2 == y3:
            out.append(x3); out.append(y3)
            continue
        est = ldc_dist(x0, y0, x1, y1) + ldc_dist(x1, y1, x2, y2) + ldc_dist(x2, y2, x3, y3)
        m = max(2, js_ceil(est / step))
        for k in range(1, m + 1):
            t = k / m
            mt = 1 - t
            out.append(mt * mt * mt * x0 + 3 * mt * mt * t * x1 + 3 * mt * t * t * x2 + t * t * t * x3)
            out.append(mt * mt * mt * y0 + 3 * mt * mt * t * y1 + 3 * mt * t * t * y2 + t * t * t * y3)
    return out


def ldc_length(p):
    L = 0
    sqrt = _sqrt
    for i in range(2, len(p), 2):
        dx = p[i] - p[i - 2]; dy = p[i + 1] - p[i - 1]
        L += sqrt(dx * dx + dy * dy)
    return L


def ldc_sample(p, s):
    """Evenly spaced samples with unit direction, flat: [x,y,ux,uy, ...]"""
    # (written with inlined arithmetic for speed; same operations, same order as the JavaScript)
    sqrt = _sqrt
    np_ = len(p) // 2
    if np_ == 0:
        return []
    cx = [p[0]]; cy = [p[1]]
    lx = p[0]; ly = p[1]
    for i in range(1, np_):
        x = p[2 * i]; y = p[2 * i + 1]
        dx = x - lx; dy = y - ly
        if sqrt(dx * dx + dy * dy) >= 0.01:
            cx.append(x); cy.append(y); lx = x; ly = y
    if len(cx) == 1 and np_ > 1:
        cx.append(p[-2]); cy.append(p[-1])
    xs = []; ys = []
    for i in range(1, len(cx)):
        ax = cx[i - 1]; ay = cy[i - 1]; bx = cx[i]; by = cy[i]
        dx = bx - ax; dy = by - ay
        L = sqrt(dx * dx + dy * dy)
        if L < 1e-9:
            continue
        n = js_ceil(L / s)
        if n < 1:
            n = 1
        xs.extend([ax + dx * k / n for k in range(n)])
        ys.extend([ay + dy * k / n for k in range(n)])
    xs.append(cx[-1]); ys.append(cy[-1])
    ns = len(xs)
    out = [0.0] * (4 * ns)
    for i in range(ns):
        a = i - 1 if i > 0 else 0
        b = i + 1 if i < ns - 1 else ns - 1
        dx = xs[b] - xs[a]; dy = ys[b] - ys[a]
        L = sqrt(dx * dx + dy * dy)
        o = 4 * i
        out[o] = xs[i]; out[o + 1] = ys[i]
        if L < 1e-9:
            out[o + 2] = 1; out[o + 3] = 0
        else:
            out[o + 2] = dx / L; out[o + 3] = dy / L
    return out


def ldc_key(p, r):
    """Direction-insensitive signature for exact-duplicate detection"""
    # The JavaScript builds "x,y;x,y;..." strings and keeps the smaller of forward/backward.
    # Tuples of the same rounded integers group paths identically and are much faster here.
    m = math.pow(10, r)
    floor = _floor
    q = [(fl + 1 if x - fl >= 0.5 else fl) for x in [v * m for v in p] for fl in (floor(x),)]
    fw = tuple(q)
    bw = [0] * len(q)
    bw[0::2] = q[-2::-2]
    bw[1::2] = q[-1::-2]
    bw = tuple(bw)
    return fw if fw < bw else bw


class LDCGrid:
    def __init__(self, cell):
        self.cell = cell
        self.map = {}

    def add(self, smp):
        c = self.cell
        mp = self.map
        floor = _floor
        for i in range(0, len(smp), 4):
            k = (floor(smp[i] / c), floor(smp[i + 1] / c))
            arr = mp.get(k)
            if arr is None:
                mp[k] = smp[i:i + 4]
            else:
                arr.extend(smp[i:i + 4])


def ldc_coverage(grid, smp, d, cosTol, useDir, need):
    """Fraction of samples within d of a stored sample (optionally with parallel direction).
    Stops early once the fraction can no longer reach "need"."""
    n = len(smp) // 4
    if n == 0:
        return float("nan")   # JS: 0/0
    hit = 0
    miss = 0
    maxMiss = _floor(n * (1 - need))
    cell = grid.cell
    mp = grid.map
    d2 = d * d
    for i in range(n):
        o = i * 4
        sx = smp[o]; sy = smp[o + 1]; ux = smp[o + 2]; uy = smp[o + 3]
        cx = _floor(sx / cell); cy = _floor(sy / cell)
        found = False
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                arr = mp.get((cx + di, cy + dj))
                if arr is None:
                    continue
                for q in range(0, len(arr), 4):
                    dx = arr[q] - sx
                    dy = arr[q + 1] - sy
                    if dx * dx + dy * dy > d2:
                        continue
                    if not useDir:
                        found = True
                        break
                    dot = arr[q + 2] * ux + arr[q + 3] * uy
                    if dot < 0:
                        dot = -dot
                    if dot >= cosTol:
                        found = True
                        break
                if found:
                    break
            if found:
                break
        if found:
            hit += 1
        else:
            miss += 1
            if miss > maxMiss:
                return hit / n
    return hit / n


def ldc_end_dir(p, atStart, back):
    """Unit vector pointing OUT of the path at one end, measured over "back" pt"""
    np_ = len(p) // 2
    acc = 0
    have = False
    px = py = 0
    if atStart:
        ex = p[0]; ey = p[1]
        for i in range(1, np_):
            acc += ldc_dist(p[2 * i - 2], p[2 * i - 1], p[2 * i], p[2 * i + 1])
            px = p[2 * i]; py = p[2 * i + 1]; have = True
            if acc >= back:
                break
    else:
        ex = p[2 * np_ - 2]; ey = p[2 * np_ - 1]
        for i in range(np_ - 2, -1, -1):
            acc += ldc_dist(p[2 * i + 2], p[2 * i + 3], p[2 * i], p[2 * i + 1])
            px = p[2 * i]; py = p[2 * i + 1]; have = True
            if acc >= back:
                break
    if not have:
        return (1, 0)
    L = ldc_dist(px, py, ex, ey)
    if L < 1e-12:
        return (1, 0)
    return ((ex - px) / L, (ey - py) / L)


def ldc_chain(info, active, S):
    """Join pieces whose endpoints touch into chains that continue smoothly (turn <= maxTurnDeg)."""
    tol = S["joinTol"]
    cell = max(tol, 1e-6)
    ends = {}
    chainOf = []
    cosTurn = math.cos(S["maxTurnDeg"] * math.pi / 180)
    n = len(info)
    E = []
    for k in range(n):
        chainOf.append(-1); E.append(None)
        if not active[k]:
            continue
        pts = info[k]["pts"]
        if len(pts) < 4:
            continue
        d0 = ldc_end_dir(pts, True, S["dirBack"])
        d1 = ldc_end_dir(pts, False, S["dirBack"])
        E[k] = (pts[0], pts[1], pts[-2], pts[-1], d0[0], d0[1], d1[0], d1[1])
        for e in range(2):
            key = (_floor(E[k][2 * e] / cell), _floor(E[k][2 * e + 1] / cell))
            lst = ends.get(key)
            if lst is None:
                lst = []
                ends[key] = lst
            lst.append(k); lst.append(e)

    def best_next(k, e):
        Ek = E[k]
        px = Ek[2 * e]; py = Ek[2 * e + 1]; dx = Ek[4 + 2 * e]; dy = Ek[5 + 2 * e]
        cx = _floor(px / cell); cy = _floor(py / cell)
        bestDot = cosTurn
        bestM = -1; bestE = -1
        for i in (-1, 0, 1):
            for j in (-1, 0, 1):
                arr = ends.get((cx + i, cy + j))
                if arr is None:
                    continue
                for q in range(0, len(arr), 2):
                    m = arr[q]; me = arr[q + 1]
                    if m == k or chainOf[m] != -1:
                        continue
                    Em = E[m]
                    if ldc_dist(px, py, Em[2 * me], Em[2 * me + 1]) > tol:
                        continue
                    dot = -(dx * Em[4 + 2 * me] + dy * Em[5 + 2 * me])
                    if dot >= bestDot:
                        bestDot = dot; bestM = m; bestE = me
        return bestM, bestE

    chains = []
    for k in range(n):
        if not active[k] or chainOf[k] != -1 or len(info[k]["pts"]) < 4:
            continue
        c = len(chains)
        chainOf[k] = c
        sides = ([], [])
        for side in range(2):
            curK = k; curE = side
            while True:
                bm, be = best_next(curK, curE)
                if bm < 0:
                    break
                chainOf[bm] = c
                sides[side].append(bm)
                curK = bm; curE = 1 - be
        members = list(reversed(sides[0])) + [k] + sides[1]
        L = 0
        for t in members:
            L += info[t]["len"]
        chains.append({"members": members, "len": L})
    for k in range(n):
        if not active[k]:
            continue
        if chainOf[k] == -1:
            chainOf[k] = len(chains)
            chains.append({"members": [k], "len": info[k]["len"]})
        info[k]["chain"] = chainOf[k]
        info[k]["chainLen"] = chains[chainOf[k]]["len"]
    return chains


def ldc_seg_dist(px, py, ax, ay, bx, by):
    dx = bx - ax; dy = by - ay
    L2 = dx * dx + dy * dy
    t = 0
    if L2 > 0:
        t = ((px - ax) * dx + (py - ay) * dy) / L2
        if t < 0:
            t = 0
        elif t > 1:
            t = 1
    return ldc_dist(px, py, ax + t * dx, ay + t * dy)


class LDCSegGrid:
    """Segment grid for "does this point touch a line" tests"""

    def __init__(self, cell):
        self.cell = cell
        self.map = {}
        self.only = None
        self.coarse = None

    COARSE = 16   # coarse cell = 16 x 16 cells, used only to skip paths far from every candidate

    def add_seg(self, id_, ax, ay, bx, by):
        c = self.cell
        cx0 = _floor(min(ax, bx) / c); cx1 = _floor(max(ax, bx) / c)
        cy0 = _floor(min(ay, by) / c); cy1 = _floor(max(ay, by) / c)
        only = self.only
        mp = self.map
        for x in range(cx0, cx1 + 1):
            for y in range(cy0, cy1 + 1):
                k = (x, y)
                if only is not None and k not in only:
                    continue
                arr = mp.get(k)
                if arr is None:
                    arr = []
                    mp[k] = arr
                arr.extend((id_, ax, ay, bx, by))

    def add_path(self, id_, p):
        c = self.cell
        sqrt = _sqrt
        floor = _floor
        only = self.only
        add_seg = self.add_seg
        if only is not None and len(p) >= 2:
            # Skip the whole path if its bounding box (plus one cell) holds no queried cell
            F = self.COARSE
            coarse = self.coarse
            xs = p[0::2]; ys = p[1::2]
            gx0 = (floor(min(xs) / c) - 1) // F; gx1 = (floor(max(xs) / c) + 1) // F
            gy0 = (floor(min(ys) / c) - 1) // F; gy1 = (floor(max(ys) / c) + 1) // F
            if (gx1 - gx0 + 1) * (gy1 - gy0 + 1) <= 64:
                hit = False
                for gx in range(gx0, gx1 + 1):
                    for gy in range(gy0, gy1 + 1):
                        if (gx, gy) in coarse:
                            hit = True
                            break
                    if hit:
                        break
                if not hit:
                    return
        for i in range(2, len(p), 2):
            ax = p[i - 2]; ay = p[i - 1]; bx = p[i]; by = p[i + 1]
            dx = bx - ax; dy = by - ay
            segL = sqrt(dx * dx + dy * dy)
            if segL > c:
                m = js_ceil(segL / c)
                px = ax; py = ay
                for t in range(1, m + 1):
                    qx = ax + (bx - ax) * t / m; qy = ay + (by - ay) * t / m
                    # quick skip: a piece no longer than a cell spans at most 2x2 cells
                    if only is not None:
                        x0 = floor(min(px, qx) / c); y0 = floor(min(py, qy) / c)
                        x1 = floor(max(px, qx) / c); y1 = floor(max(py, qy) / c)
                        if (x1 - x0 <= 1 and y1 - y0 <= 1 and
                                (x0, y0) not in only and (x1, y1) not in only and
                                (x0, y1) not in only and (x1, y0) not in only):
                            px = qx; py = qy
                            continue
                    add_seg(id_, px, py, qx, qy)
                    px = qx; py = qy
                continue
            add_seg(id_, ax, ay, bx, by)

    def touches(self, px, py, tol, self_id, verdict, mode):
        """mode 0: only kept lines count; mode 1: any line that existed before (not a duplicate)"""
        cx = _floor(px / self.cell); cy = _floor(py / self.cell)
        for i in (-1, 0, 1):
            for j in (-1, 0, 1):
                arr = self.map.get((cx + i, cy + j))
                if arr is None:
                    continue
                for q in range(0, len(arr), 5):
                    id_ = arr[q]
                    if id_ == self_id:
                        continue
                    v = verdict[id_]
                    if (v != "keep") if mode == 0 else (v == "dup"):
                        continue
                    if ldc_seg_dist(px, py, arr[q + 1], arr[q + 2], arr[q + 3], arr[q + 4]) <= tol:
                        return True
        return False


def ldc_orphans(info, verdict, S, chains):
    """Remove short kept pieces left dangling by the removals. Repeats until nothing changes."""
    sg = LDCSegGrid(max(0.2, S["touchTol"] * 4))
    n = len(info)
    cand = []
    only = set()
    for k in range(n):
        if info[k]["len"] > S["orphanMaxLength"] or verdict[k] != "keep" or info[k]["locked"] or len(info[k]["pts"]) < 4:
            continue
        cand.append(k)
        pp = info[k]["pts"]
        for e in range(2):
            cx = _floor((pp[0] if e == 0 else pp[-2]) / sg.cell)
            cy = _floor((pp[1] if e == 0 else pp[-1]) / sg.cell)
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    only.add((cx + di, cy + dj))
    if not cand:
        return
    sg.only = only
    F = sg.COARSE
    sg.coarse = set((x // F, y // F) for (x, y) in only)
    for k in range(n):
        if verdict[k] != "dup":
            sg.add_path(k, info[k]["pts"])
    changed = True
    npass = 0
    while changed and npass < 10:
        changed = False
        npass += 1
        for k in cand:
            if verdict[k] != "keep" or info[k]["locked"] or len(info[k]["pts"]) < 4:
                continue
            aliveLen = info[k]["len"]
            if chains is not None and info[k].get("chain") is not None:
                mem = chains[info[k]["chain"]]["members"]
                pos = 0
                for t in range(len(mem)):
                    if mem[t] == k:
                        pos = t
                t = pos - 1
                while t >= 0 and verdict[mem[t]] == "keep":
                    aliveLen += info[mem[t]]["len"]; t -= 1
                t = pos + 1
                while t < len(mem) and verdict[mem[t]] == "keep":
                    aliveLen += info[mem[t]]["len"]; t += 1
            if aliveLen > S["orphanMaxLength"]:
                continue
            p = info[k]["pts"]
            dangling = False
            for e in range(2):
                ex = p[0] if e == 0 else p[-2]
                ey = p[1] if e == 0 else p[-1]
                if sg.touches(ex, ey, S["touchTol"], k, verdict, 0):
                    continue
                if sg.touches(ex, ey, S["touchTol"], k, verdict, 1):
                    dangling = True
                    break
            if dangling:
                verdict[k] = "orphan"
                changed = True


def ldc_run(paths, S, progress=None):
    n = len(paths)
    verdict = []
    info = []
    cosTol = math.cos(S["angleTolDeg"] * math.pi / 180)
    # 1. Flatten
    for i in range(n):
        pts = ldc_flatten(paths[i]["pp"], paths[i]["closed"], S["flattenStep"])
        info.append({"i": i, "pts": pts, "len": ldc_length(pts), "locked": bool(paths[i].get("locked"))})
        verdict.append("keep")
    if progress:
        progress("Prepared geometry")
    # 2. Exact duplicates: keep one per group (unlocked loses to locked; otherwise the first one)
    if S["removeDuplicates"]:
        groups = {}
        for i in range(n):
            groups.setdefault(ldc_key(info[i]["pts"], S["dupDecimals"]), []).append(info[i])
        for g in groups.values():
            if len(g) < 2:
                continue
            g.sort(key=lambda a: (not a["locked"], a["i"]))
            for j in range(1, len(g)):
                if not g[j]["locked"]:
                    verdict[g[j]["i"]] = "dup"
        groups = None
    if progress:
        progress("Found duplicates")
    # 3. Near-parallel lines: greedy, longest continuous line first
    order = []
    active = []
    for i in range(n):
        active.append(verdict[i] == "keep")
        if verdict[i] == "keep":
            order.append(info[i])
    chains = None
    if S["useChains"]:
        chains = ldc_chain(info, active, S)
    else:
        for i in range(n):
            info[i]["chain"] = i
            info[i]["chainLen"] = info[i]["len"]
    if progress:
        progress("Joined line pieces")
    order.sort(key=lambda a: (not a["locked"], -a["chainLen"], a["chain"], -a["len"]))
    grid = LDCGrid(max(S["nearDist"], S["stubDist"]))
    stubCandidates = []
    for i, o in enumerate(order):
        if progress and i % 5000 == 0 and i:
            progress("Comparing lines %d / %d" % (i, len(order)))
        smp = ldc_sample(o["pts"], S["sampleStep"])
        if not o["locked"] and S["removeNearParallel"]:
            cov = ldc_coverage(grid, smp, S["nearDist"], cosTol, True, S["nearCoverage"])
            if cov >= S["nearCoverage"]:
                verdict[o["i"]] = "near"
                continue
        if not o["locked"] and S["removeStubs"] and o["chainLen"] <= S["stubMaxLength"]:
            o["smp"] = smp
            stubCandidates.append(o)
            continue
        grid.add(smp)
    # 4. Stubs: short paths that lie (any direction) almost entirely on kept lines
    for o in stubCandidates:
        cov = ldc_coverage(grid, o["smp"], S["stubDist"], 0, False, S["stubCoverage"])
        if cov >= S["stubCoverage"]:
            verdict[o["i"]] = "stub"
        else:
            grid.add(o["smp"])
    grid = None
    if progress:
        progress("Compared lines")
    # 5. Fragments left dangling by the removals
    if S["removeOrphans"]:
        ldc_orphans(info, verdict, S, chains)
    return verdict


# =====================================================================================================
# v2: gap bridging (not in the Illustrator script)
# A "dangling end" is an end of a kept open line that touches no other kept line (within touchTol).
# It is bridged with a short straight line when something it should meet lies within gapMax:
#   1. another dangling end, facing it         -> end-to-end bridge (closest pairs first)
#   2. a kept line straight ahead of it        -> the line is extended to meet it
#   3. the nearest point of a kept line, within bridgeMaxAngleDeg of the line's direction
# "created" = the end used to touch a line this script removed; otherwise the gap was in the original.
# =====================================================================================================

def ldc_bridges(paths, verdict, S):
    gapMax = S["gapMax"]
    touchTol = S["touchTol"]
    snap = S["bridgeAnyAngleBelow"]
    cosA = math.cos(S["bridgeMaxAngleDeg"] * math.pi / 180)
    n = len(paths)
    pts = [None] * n
    for i in range(n):
        if verdict[i] != "dup":
            pts[i] = ldc_flatten(paths[i]["pp"], paths[i]["closed"], S["flattenStep"])

    # Ends of kept open lines, with outward direction
    ends = []   # [path, x, y, ox, oy]
    for i in range(n):
        p = pts[i]
        if verdict[i] != "keep" or p is None or len(p) < 4 or paths[i]["closed"]:
            continue
        if ldc_dist(p[0], p[1], p[-2], p[-1]) <= touchTol:
            continue   # closed loop drawn as an open line
        d0 = ldc_end_dir(p, True, S["dirBack"])
        d1 = ldc_end_dir(p, False, S["dirBack"])
        ends.append((i, p[0], p[1], d0[0], d0[1]))
        ends.append((i, p[-2], p[-1], d1[0], d1[1]))
    if not ends:
        return [], 0

    sg = LDCSegGrid(max(gapMax, S["touchTol"] * 4, 0.2))
    c = sg.cell
    only = set()
    for (i, x, y, ox, oy) in ends:
        cx = _floor(x / c); cy = _floor(y / c)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                only.add((cx + di, cy + dj))
    sg.only = only
    F = sg.COARSE
    sg.coarse = set((x // F, y // F) for (x, y) in only)
    for i in range(n):
        if pts[i] is not None:
            sg.add_path(i, pts[i])

    dangling = []   # (path, x, y, ox, oy, created)
    for (i, x, y, ox, oy) in ends:
        if sg.touches(x, y, touchTol, i, verdict, 0):
            continue
        dangling.append((i, x, y, ox, oy, sg.touches(x, y, touchTol, i, verdict, 1)))

    def facing(ox, oy, vx, vy, d):
        return d <= snap or (ox * vx + oy * vy) / d >= cosA

    # 1. End to end
    eg = {}
    for k, (i, x, y, ox, oy, cr) in enumerate(dangling):
        eg.setdefault((_floor(x / c), _floor(y / c)), []).append(k)
    pairs = []
    lens = {}
    for a, (ia, xa, ya, oxa, oya, cra) in enumerate(dangling):
        cx = _floor(xa / c); cy = _floor(ya / c)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for b in eg.get((cx + di, cy + dj), ()):
                    if b <= a:
                        continue
                    ib, xb, yb, oxb, oyb, crb = dangling[b]
                    vx = xb - xa; vy = yb - ya
                    d = _sqrt(vx * vx + vy * vy)
                    if d > gapMax:
                        continue
                    if ia == ib:   # the two ends of one line: only close it if the line is long
                        if ia not in lens:
                            lens[ia] = ldc_length(pts[ia])
                        if lens[ia] <= 4 * gapMax:
                            continue
                    if facing(oxa, oya, vx, vy, d) and facing(oxb, oyb, -vx, -vy, d):
                        pairs.append((d, a, b))
    pairs.sort()
    used = set()
    bridges = []
    for d, a, b in pairs:
        if a in used or b in used:
            continue
        used.add(a); used.add(b)
        ia, xa, ya, _, _, cra = dangling[a]
        ib, xb, yb, _, _, crb = dangling[b]
        bridges.append({"path": ia, "x0": xa, "y0": ya, "x1": xb, "y1": yb, "kind": "end", "created": cra or crb})

    # 2./3. End to line
    for k, (i, x, y, ox, oy, cr) in enumerate(dangling):
        if k in used:
            continue
        cx = _floor(x / c); cy = _floor(y / c)
        best_ray = None    # (t, hx, hy)
        best_near = None   # (d, qx, qy)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                arr = sg.map.get((cx + di, cy + dj))
                if arr is None:
                    continue
                for q in range(0, len(arr), 5):
                    id_ = arr[q]
                    if id_ == i or verdict[id_] != "keep":
                        continue
                    ax = arr[q + 1]; ay = arr[q + 2]; bx = arr[q + 3]; by = arr[q + 4]
                    sx = bx - ax; sy = by - ay
                    # ray x + t*o hits segment a + u*s ?
                    den = ox * sy - oy * sx
                    if abs(den) > 1e-12:
                        wx = ax - x; wy = ay - y
                        t = (wx * sy - wy * sx) / den
                        u = (wx * oy - wy * ox) / den
                        if 0 <= u <= 1 and 0 < t <= gapMax and (best_ray is None or t < best_ray[0]):
                            best_ray = (t, x + t * ox, y + t * oy)
                    # nearest point on the segment
                    L2 = sx * sx + sy * sy
                    u = 0
                    if L2 > 0:
                        u = ((x - ax) * sx + (y - ay) * sy) / L2
                        u = 0 if u < 0 else (1 if u > 1 else u)
                    qx = ax + u * sx; qy = ay + u * sy
                    vx = qx - x; vy = qy - y
                    d = _sqrt(vx * vx + vy * vy)
                    if d <= gapMax and facing(ox, oy, vx, vy, d) and (best_near is None or d < best_near[0]):
                        best_near = (d, qx, qy)
        if best_near is not None and best_near[0] <= snap:
            tx, ty = best_near[1], best_near[2]
        elif best_ray is not None:
            tx, ty = best_ray[1], best_ray[2]
        elif best_near is not None:
            tx, ty = best_near[1], best_near[2]
        else:
            continue
        used.add(k)
        bridges.append({"path": i, "x0": x, "y0": y, "x1": tx, "y1": ty, "kind": "line", "created": cr})

    return bridges, len(dangling) - len(used)


# =====================================================================================================
# DXF side
# =====================================================================================================

REASON_LAYERS = {
    "dup": ("LDC_Duplicates", 1),        # red
    "near": ("LDC_Near-parallel", 5),    # blue
    "orphan": ("LDC_Fragments", 6),      # magenta
    "stub": ("LDC_Stubs", 3),            # green
}
BRIDGE_LAYER = ("LDC_Bridges", 4)     # cyan
REASON_NAMES = {"dup": "Duplicates", "near": "Near-parallel", "orphan": "Fragments", "stub": "Stubs"}

# Entity types read as lines. Everything else (text, dimensions, hatches, points...) is left untouched.
LINE_TYPES = {"LINE", "ARC", "CIRCLE", "ELLIPSE", "SPLINE", "LWPOLYLINE", "POLYLINE"}

_UNIT_PT = {"pt": 1.0, "in": 72.0, "mm": 72.0 / 25.4, "cm": 72.0 / 2.54}


def parse_length_pt(text):
    """'4in' / '100mm' / '288pt' / '10cm' -> points. A bare number is taken as inches."""
    t = str(text).strip().lower().replace(" ", "")
    for u in ("pt", "in", "mm", "cm"):
        if t.endswith(u):
            return float(t[: -len(u)]) * _UNIT_PT[u]
    if t.endswith('"'):
        return float(t[:-1]) * 72.0
    return float(t) * 72.0


def entity_to_pps(entity, ezpath):
    """DXF entity -> list of (pp, closed) in drawing units, cubic Beziers like Illustrator uses."""
    path = ezpath.make_path(entity)
    subs = list(path.sub_paths()) if path.has_sub_paths else [path]
    out = []
    for sp in subs:
        if len(sp) == 0:
            continue
        s = sp.start
        pp = [s.x, s.y, s.x, s.y, s.x, s.y]
        for cmd in sp.commands():
            t = cmd.type
            e = cmd.end
            if t == ezpath.Command.LINE_TO:
                pp.extend((e.x, e.y, e.x, e.y, e.x, e.y))
            elif t == ezpath.Command.CURVE4_TO:
                pp[-2] = cmd.ctrl1.x; pp[-1] = cmd.ctrl1.y
                pp.extend((e.x, e.y, cmd.ctrl2.x, cmd.ctrl2.y, e.x, e.y))
            elif t == ezpath.Command.CURVE3_TO:
                x0 = pp[-6]; y0 = pp[-5]; c = cmd.ctrl
                pp[-2] = x0 + 2.0 / 3.0 * (c.x - x0); pp[-1] = y0 + 2.0 / 3.0 * (c.y - y0)
                pp.extend((e.x, e.y, e.x + 2.0 / 3.0 * (c.x - e.x), e.y + 2.0 / 3.0 * (c.y - e.y), e.x, e.y))
            else:   # MOVE_TO inside a sub path should not happen; start a new piece
                if len(pp) >= 12:
                    out.append((pp, False))
                pp = [e.x, e.y, e.x, e.y, e.x, e.y]
        if len(pp) >= 6:
            out.append((pp, False))
    return out


def explode_inserts(layout, log):
    """Explode block references (recursively) so every line is its own entity."""
    total = 0
    for _ in range(20):
        inserts = layout.query("INSERT")
        if len(inserts) == 0:
            break
        for ins in inserts:
            try:
                ins.explode()
                total += 1
            except Exception as ex:   # e.g. non-uniform scaling the library can't handle
                log("   could not explode block %s: %s" % (ins.dxf.name, ex))
    return total


def process_file(src, width_pt, scale, layers, S, explode=True, out_dir=None, quiet=False):
    import ezdxf
    from ezdxf import path as ezpath
    from ezdxf import bbox as ezbbox

    t0 = time.time()

    def log(msg):
        if not quiet:
            print("[%5.1f s] %s" % (time.time() - t0, msg), flush=True)

    log("Reading " + src)
    doc = ezdxf.readfile(src)
    want = None if not layers else set(l.lower() for l in layers)

    layouts = [doc.modelspace()] + [l for l in doc.layouts if not l.is_modelspace]
    report = []
    removed_entities = []   # (entity, reason, layout)
    bridges = []            # (layout, source entity, x0, y0, x1, y1) in drawing units
    any_geometry = False

    for layout in layouts:
        if explode:
            nx = explode_inserts(layout, log)
            if nx:
                log("%s: exploded %d block references" % (layout.name, nx))
        ents = [e for e in layout if e.dxftype() in LINE_TYPES and (want is None or e.dxf.layer.lower() in want)]
        if not ents:
            continue
        any_geometry = True

        # Scale: points per drawing unit
        if scale:
            s = scale
        else:
            ext = ezbbox.extents(ents)
            w = ext.size.x if ext.has_data else 0
            if w <= 0:
                log("%s: geometry has no width, skipped" % layout.name)
                continue
            s = width_pt / w
        log("%s: %d lines, scale %.6g pt per drawing unit" % (layout.name, len(ents), s))

        paths = []
        owner = []
        failed = 0
        for idx, e in enumerate(ents):
            try:
                pps = entity_to_pps(e, ezpath)
            except Exception:
                failed += 1
                continue
            for pp, closed in pps:
                paths.append({"closed": closed, "pp": [v * s for v in pp], "locked": False})
                owner.append(idx)
        if failed:
            log("   %d entities could not be read and were kept as-is" % failed)

        verdict = ldc_run(paths, S, (lambda m: log("   " + m)) if not quiet else None)

        # An entity is removed only if every piece of it was removed (first piece's reason is used)
        ent_v = {}
        for v, idx in zip(verdict, owner):
            cur = ent_v.get(idx)
            if cur is None:
                ent_v[idx] = v
            elif v == "keep":
                ent_v[idx] = "keep"
        counts = {"dup": 0, "near": 0, "orphan": 0, "stub": 0}
        for idx, v in ent_v.items():
            if v != "keep":
                counts[v] += 1
                removed_entities.append((ents[idx], v, layout))
        # v2: bridge small gaps between the kept lines
        nb = {"end": 0, "line": 0, "created": 0, "existing": 0, "left": 0}
        if S.get("bridgeGaps"):
            eff = [("keep" if ent_v.get(idx) == "keep" else v) for v, idx in zip(verdict, owner)]
            br, left = ldc_bridges(paths, eff, S)
            nb["left"] = left
            for b in br:
                src_e = ents[owner[b["path"]]]
                bridges.append((layout, src_e, b["x0"] / s, b["y0"] / s, b["x1"] / s, b["y1"] / s))
                nb[b["kind"]] += 1
                nb["created" if b["created"] else "existing"] += 1
            log("   Bridged %d gaps (%d created by the cleanup, %d already in the file); %d line ends left open"
                % (len(br), nb["created"], nb["existing"], left))
        report.append((layout.name, len(ents), counts, nb))

    if not any_geometry:
        names = sorted(l.dxf.name for l in doc.layers)
        raise SystemExit("No lines found%s. Layers in this file: %s" %
                         (" on layers " + ", ".join(layers) if layers else "", ", ".join(names)))

    base = os.path.splitext(os.path.basename(src))[0]
    folder = out_dir or os.path.dirname(os.path.abspath(src))
    clean_path = os.path.join(folder, base + "_clean.dxf")
    review_path = os.path.join(folder, base + "_review.dxf")

    # Review file: removed lines on colored layers
    for v in sorted(set(v for _, v, _ in removed_entities)):
        name, color = REASON_LAYERS[v]
        if name not in doc.layers:
            doc.layers.add(name, color=color)
    for e, v, _ in removed_entities:
        e.dxf.layer = REASON_LAYERS[v][0]
        e.dxf.color = 256          # BYLAYER, so the reason color shows
        if e.dxf.hasattr("true_color"):
            e.dxf.discard("true_color")
    # Bridges: in the review file on their own layer, in the clean file on the source line's layer
    new_bridges = []
    if bridges:
        if BRIDGE_LAYER[0] not in doc.layers:
            doc.layers.add(BRIDGE_LAYER[0], color=BRIDGE_LAYER[1])
        for layout, src_e, x0, y0, x1, y1 in bridges:
            new_bridges.append((layout.add_line((x0, y0), (x1, y1), dxfattribs={"layer": BRIDGE_LAYER[0], "color": 256}), src_e))
    doc.saveas(review_path)

    # Clean file: removed lines deleted
    for e, v, layout in removed_entities:
        layout.delete_entity(e)
    for b, src_e in new_bridges:
        b.dxf.layer = src_e.dxf.layer
        for attr in ("color", "true_color", "linetype", "lineweight"):
            if src_e.dxf.hasattr(attr):
                b.dxf.set(attr, src_e.dxf.get(attr))
    for name, _ in list(REASON_LAYERS.values()) + [BRIDGE_LAYER]:
        if name in doc.layers:
            doc.layers.remove(name)
    doc.saveas(clean_path)

    lines = ["LineDensityCleanUp (DXF) finished in %.1f s" % (time.time() - t0), "File: " + src]
    tot = {"dup": 0, "near": 0, "orphan": 0, "stub": 0}
    btot = {"end": 0, "line": 0, "created": 0, "existing": 0, "left": 0}
    checked = 0
    for name, n, c, nb in report:
        checked += n
        for k in tot:
            tot[k] += c[k]
        for k in btot:
            btot[k] += nb[k]
    lines.append("Lines checked: %d" % checked)
    for k in ("dup", "near", "orphan", "stub"):
        if k != "stub" or tot[k]:
            lines.append("%s removed: %d" % (REASON_NAMES[k], tot[k]))
    if S.get("bridgeGaps"):
        lines.append("Gaps bridged: %d (%d created by the cleanup, %d already in the file)"
                     % (btot["created"] + btot["existing"], btot["created"], btot["existing"]))
        lines.append("Line ends still open: %d" % btot["left"])
    lines.append("Clean file:  " + clean_path)
    lines.append("Review file: " + review_path)
    if not quiet:
        print("\n" + "\n".join(lines) + "\n")
    return {"checked": checked, "removed": tot, "bridges": btot, "clean": clean_path, "review": review_path}


def main(argv=None):
    import argparse
    import glob

    ap = argparse.ArgumentParser(description="Remove duplicate, near-parallel and fragment lines from DXF files "
                                             "before importing them into Illustrator.")
    ap.add_argument("files", nargs="+", help="DXF file(s); wildcards like *.dxf are fine")
    ap.add_argument("--width", help="final printed width of the figure, e.g. 4in, 100mm, 288pt (bare number = inches)")
    ap.add_argument("--scale", type=float, help="instead of --width: points per drawing unit at final size")
    ap.add_argument("--layers", help="only clean these DXF layers, comma-separated (default: all layers)")
    ap.add_argument("--no-explode", action="store_true", help="leave block references alone (their lines are not checked)")
    ap.add_argument("--gap", help="largest gap to bridge, e.g. 0.5pt (default %gpt)" % SETTINGS["gapMax"])
    ap.add_argument("--no-bridge", action="store_true", help="do not bridge gaps (same output as v1)")
    ap.add_argument("--out-dir", help="folder for the output files (default: next to each input)")
    args = ap.parse_args(argv)

    files = []
    for f in args.files:
        hits = glob.glob(f)
        files.extend(hits if hits else [f])
    files = [f for f in files if not os.path.splitext(f)[0].endswith(("_clean", "_review"))]

    width_pt = None
    if not args.scale:
        width = args.width
        if not width:
            if not sys.stdin.isatty():
                ap.error("give the final size with --width (e.g. --width 4in) or --scale")
            width = input("Final printed width of the figure (e.g. 4in, 100mm): ")
        width_pt = parse_length_pt(width)
        if width_pt <= 0:
            ap.error("width must be greater than 0")

    layers = [l.strip() for l in args.layers.split(",")] if args.layers else None
    try:
        import ezdxf  # noqa: F401
    except ImportError:
        sys.exit("This script needs the ezdxf library. Install it with:  pip install ezdxf")

    S = dict(SETTINGS)
    if args.no_bridge:
        S["bridgeGaps"] = False
    if args.gap:
        S["gapMax"] = parse_length_pt(args.gap if args.gap.strip()[-1].isalpha() else args.gap + "pt")
    for f in files:
        process_file(f, width_pt, args.scale, layers, S, explode=not args.no_explode, out_dir=args.out_dir)


if __name__ == "__main__":
    main()
