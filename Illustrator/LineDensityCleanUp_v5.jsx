//@target illustrator
// LineDensityCleanUp v5 - removes duplicate, near-parallel and leftover fragment lines from the layer(s) named in SETTINGS (default: origin).
// Removed lines are MOVED (not deleted) to a hidden layer "Removed by LineDensityCleanUp", one sublayer per reason.
// Run on a copy of the file. If anything is selected, only selected lines can be removed.
// Progress is written to LineDensityCleanUp_log.txt next to the .ai file (or on the Desktop if the file is unsaved).
// v3: same results as v2, faster (flat number arrays, fewer objects, fragment check limited to short pieces).
// v4: same results as v3; drops the group-and-move step, which failed in Illustrator and cost about 3 minutes.
// v5: works on one layer, "origin" (capitalization ignored). Drops the Edges-over-Tangent tie-break for duplicates,
//     which only applied when copies sat on two layers. Detection logic and distances unchanged from v4.
//     If the layer isn't found, the message lists the layers the file does have.

// ===== LineDensityCleanUp core v3 (ES3: runs unchanged in Illustrator ExtendScript and in Node) =====
// Input:  paths = [{layer:<layer name>, closed:bool, pp:[ax,ay,lx,ly,rx,ry, ax,ay,...] (flat), locked:bool}]
//         (locked = context only: compared against, never removed)
// Output: array of verdicts, same order: "keep" | "dup" | "near" | "stub" | "orphan"
// v3: all geometry is kept in flat number arrays. ExtendScript slows down sharply as the number of
//     live objects grows, so v3 avoids creating one small array per point. Results are identical to v2.

function LDC_dist(ax, ay, bx, by) { var dx = bx - ax, dy = by - ay; return Math.sqrt(dx*dx + dy*dy); }

// Flatten bezier path points (flat, 6 per point) to a flat polyline [x,y,x,y,...]
function LDC_flatten(pp, closed, step) {
    var out = [], n = pp.length / 6, segs = closed ? n : n - 1, i, k, a, b, m, t, mt;
    if (n === 0) return out;
    out.push(pp[0], pp[1]);
    for (i = 0; i < segs; i++) {
        a = i * 6; b = ((i + 1) % n) * 6;
        var x0 = pp[a], y0 = pp[a+1], x1 = pp[a+4], y1 = pp[a+5], x2 = pp[b+2], y2 = pp[b+3], x3 = pp[b], y3 = pp[b+1];
        var straight = (x1 === x0 && y1 === y0 && x2 === x3 && y2 === y3);
        if (straight) { out.push(x3, y3); continue; }
        var est = LDC_dist(x0, y0, x1, y1) + LDC_dist(x1, y1, x2, y2) + LDC_dist(x2, y2, x3, y3);
        m = Math.max(2, Math.ceil(est / step));
        for (k = 1; k <= m; k++) {
            t = k / m; mt = 1 - t;
            out.push(mt*mt*mt*x0 + 3*mt*mt*t*x1 + 3*mt*t*t*x2 + t*t*t*x3,
                     mt*mt*mt*y0 + 3*mt*mt*t*y1 + 3*mt*t*t*y2 + t*t*t*y3);
        }
    }
    return out;
}

function LDC_length(p) {
    var L = 0, i;
    for (i = 2; i < p.length; i += 2) L += LDC_dist(p[i-2], p[i-1], p[i], p[i+1]);
    return L;
}

// Evenly spaced samples with unit direction, flat: [x,y,ux,uy, x,y,ux,uy, ...]
// Micro-segments (< 0.01 pt) are skipped; direction is taken across neighboring samples.
function LDC_sample(p, s) {
    var clean = [], i, k, n, L, pos = [], np = p.length / 2;
    for (i = 0; i < np; i++) {
        if (clean.length === 0 || LDC_dist(clean[clean.length-2], clean[clean.length-1], p[2*i], p[2*i+1]) >= 0.01) clean.push(p[2*i], p[2*i+1]);
    }
    if (clean.length === 2 && np > 1) clean.push(p[p.length-2], p[p.length-1]);
    for (i = 2; i < clean.length; i += 2) {
        var ax = clean[i-2], ay = clean[i-1], bx = clean[i], by = clean[i+1];
        L = LDC_dist(ax, ay, bx, by);
        if (L < 1e-9) continue;
        n = Math.max(1, Math.ceil(L / s));
        for (k = 0; k < n; k++) pos.push(ax + (bx - ax) * k / n, ay + (by - ay) * k / n);
    }
    if (clean.length > 0) pos.push(clean[clean.length-2], clean[clean.length-1]);
    var out = [], a, b, ux, uy, ns = pos.length / 2;
    for (i = 0; i < ns; i++) {
        a = Math.max(0, i - 1) * 2; b = Math.min(ns - 1, i + 1) * 2;
        L = LDC_dist(pos[a], pos[a+1], pos[b], pos[b+1]);
        if (L < 1e-9) { ux = 1; uy = 0; } else { ux = (pos[b] - pos[a]) / L; uy = (pos[b+1] - pos[a+1]) / L; }
        out.push(pos[2*i], pos[2*i+1], ux, uy);
    }
    return out;
}

// Direction-insensitive signature for exact-duplicate detection
function LDC_key(p, r) {
    var f = [], b = [], i, m = Math.pow(10, r);
    for (i = 0; i < p.length; i += 2) f.push(Math.round(p[i] * m) + "," + Math.round(p[i+1] * m));
    for (i = f.length - 1; i >= 0; i--) b.push(f[i]);
    var fs = f.join(";"), bs = b.join(";");
    return fs < bs ? fs : bs;
}

function LDC_Grid(cell) { this.cell = cell; this.map = {}; }
LDC_Grid.prototype.add = function (smp) {   // smp flat, 4 per sample
    var i, k, arr, c = this.cell;
    for (i = 0; i < smp.length; i += 4) {
        k = Math.floor(smp[i] / c) + "_" + Math.floor(smp[i+1] / c);
        arr = this.map[k];
        if (!arr) { arr = []; this.map[k] = arr; }
        arr.push(smp[i], smp[i+1], smp[i+2], smp[i+3]);
    }
};
// Is the sample at smp[o] within distance d of a stored sample (optionally with parallel direction)?
LDC_Grid.prototype.near = function (smp, o, d, cosTol, useDir) {
    var sx = smp[o], sy = smp[o+1], ux = smp[o+2], uy = smp[o+3];
    var cx = Math.floor(sx / this.cell), cy = Math.floor(sy / this.cell), i, j, q, arr, dx, dy, dot, d2 = d * d;
    for (i = -1; i <= 1; i++) for (j = -1; j <= 1; j++) {
        arr = this.map[(cx + i) + "_" + (cy + j)];
        if (!arr) continue;
        for (q = 0; q < arr.length; q += 4) {
            dx = arr[q] - sx; dy = arr[q + 1] - sy;
            if (dx*dx + dy*dy > d2) continue;
            if (!useDir) return true;
            dot = arr[q + 2] * ux + arr[q + 3] * uy;
            if (dot < 0) dot = -dot;
            if (dot >= cosTol) return true;
        }
    }
    return false;
};

// Fraction of samples covered; stops early once the fraction can no longer reach "need"
function LDC_coverage(grid, smp, d, cosTol, useDir, need) {
    var hit = 0, miss = 0, n = smp.length / 4, maxMiss = Math.floor(n * (1 - need)), i;
    for (i = 0; i < n; i++) {
        if (grid.near(smp, i * 4, d, cosTol, useDir)) hit++;
        else { miss++; if (miss > maxMiss) return hit / n; }
    }
    return hit / n;
}

// Unit vector pointing OUT of the path at one end, measured over "back" pt; returns [ux, uy]
function LDC_endDir(p, atStart, back) {
    var np = p.length / 2, i, acc = 0, ex, ey, px, py, have = false;
    if (atStart) {
        ex = p[0]; ey = p[1];
        for (i = 1; i < np; i++) { acc += LDC_dist(p[2*i-2], p[2*i-1], p[2*i], p[2*i+1]); px = p[2*i]; py = p[2*i+1]; have = true; if (acc >= back) break; }
    } else {
        ex = p[2*np-2]; ey = p[2*np-1];
        for (i = np - 2; i >= 0; i--) { acc += LDC_dist(p[2*i+2], p[2*i+3], p[2*i], p[2*i+1]); px = p[2*i]; py = p[2*i+1]; have = true; if (acc >= back) break; }
    }
    if (!have) return [1, 0];
    var L = LDC_dist(px, py, ex, ey);
    if (L < 1e-12) return [1, 0];
    return [(ex - px) / L, (ey - py) / L];
}

// Join pieces whose endpoints touch into chains that continue smoothly (turn <= maxTurnDeg).
// Sets info[k].chain and info[k].chainLen; returns chains [{members (in order), len}]
function LDC_chain(info, active, S, progress) {
    var tol = S.joinTol, cell = Math.max(tol, 1e-6), ends = {}, k, a, e, key, chainOf = [], cosTurn = Math.cos(S.maxTurnDeg * Math.PI / 180);
    var n = info.length, E = [];   // E: per piece, flat [x0,y0,x1,y1, dx0,dy0,dx1,dy1]
    for (k = 0; k < n; k++) {
        chainOf.push(-1); E.push(null);
        if (!active[k]) continue;
        a = info[k]; if (a.pts.length < 4) continue;
        var d0 = LDC_endDir(a.pts, true, S.dirBack), d1 = LDC_endDir(a.pts, false, S.dirBack);
        E[k] = [a.pts[0], a.pts[1], a.pts[a.pts.length-2], a.pts[a.pts.length-1], d0[0], d0[1], d1[0], d1[1]];
        for (e = 0; e < 2; e++) {
            key = Math.floor(E[k][2*e] / cell) + "_" + Math.floor(E[k][2*e+1] / cell);
            if (!ends[key]) ends[key] = [];
            ends[key].push(k, e);
        }
        if (progress && k % 2000 === 0) progress("Joining line pieces", k, n);
    }
    var bestM, bestE;
    function bestNext(k, e) {
        // piece k, leaving through end e; find unvisited piece touching that end that continues straightest
        var Ek = E[k], px = Ek[2*e], py = Ek[2*e+1], dx = Ek[4+2*e], dy = Ek[5+2*e];
        var cx = Math.floor(px / cell), cy = Math.floor(py / cell), bestDot = cosTurn, i, j, arr, q, m, me, dot, Em;
        bestM = -1; bestE = -1;
        for (i = -1; i <= 1; i++) for (j = -1; j <= 1; j++) {
            arr = ends[(cx + i) + "_" + (cy + j)]; if (!arr) continue;
            for (q = 0; q < arr.length; q += 2) {
                m = arr[q]; me = arr[q+1];
                if (m === k || chainOf[m] !== -1) continue;
                Em = E[m];
                if (LDC_dist(px, py, Em[2*me], Em[2*me+1]) > tol) continue;
                dot = -(dx * Em[4+2*me] + dy * Em[5+2*me]);   // continuing direction = opposite of m's outward dir
                if (dot >= bestDot) { bestDot = dot; bestM = m; bestE = me; }
            }
        }
        return bestM >= 0;
    }
    var chains = [], c, members, curK, curE, side, L, t, sides;
    for (k = 0; k < n; k++) {
        if (!active[k] || chainOf[k] !== -1 || info[k].pts.length < 4) continue;
        c = chains.length; chainOf[k] = c;
        sides = [[], []];
        for (side = 0; side < 2; side++) {
            curK = k; curE = side;
            while (bestNext(curK, curE)) {
                chainOf[bestM] = c; sides[side].push(bestM);
                curK = bestM; curE = 1 - bestE;
            }
        }
        members = [];   // in geometric order along the chain
        for (t = sides[0].length - 1; t >= 0; t--) members.push(sides[0][t]);
        members.push(k);
        for (t = 0; t < sides[1].length; t++) members.push(sides[1][t]);
        L = 0; for (t = 0; t < members.length; t++) L += info[members[t]].len;
        chains.push({ members: members, len: L });
        if (progress && k % 2000 === 0) progress("Joining line pieces", k, n);
    }
    for (k = 0; k < n; k++) {
        if (!active[k]) continue;
        if (chainOf[k] === -1) { chainOf[k] = chains.length; chains.push({ members: [k], len: info[k].len }); }
        info[k].chain = chainOf[k]; info[k].chainLen = chains[chainOf[k]].len;
    }
    return chains;
}

// Segment grid for "does this point touch a line" tests; flat per cell: [id,ax,ay,bx,by, ...]
function LDC_SegGrid(cell) { this.cell = cell; this.map = {}; }
LDC_SegGrid.prototype.addSeg = function (id, ax, ay, bx, by) {
    var c = this.cell, x, y, k, arr;
    var cx0 = Math.floor(Math.min(ax, bx) / c), cx1 = Math.floor(Math.max(ax, bx) / c);
    var cy0 = Math.floor(Math.min(ay, by) / c), cy1 = Math.floor(Math.max(ay, by) / c);
    for (x = cx0; x <= cx1; x++) for (y = cy0; y <= cy1; y++) {
        k = x + "_" + y;
        if (this.only && !this.only[k]) continue;   // only index cells that will be queried
        arr = this.map[k];
        if (!arr) { arr = []; this.map[k] = arr; }
        arr.push(id, ax, ay, bx, by);
    }
};
LDC_SegGrid.prototype.addPath = function (id, p) {
    var i, c = this.cell, ax, ay, bx, by, segL, m, t;
    for (i = 2; i < p.length; i += 2) {
        ax = p[i-2]; ay = p[i-1]; bx = p[i]; by = p[i+1];
        segL = LDC_dist(ax, ay, bx, by);
        if (segL > c) {   // split long segments so each piece only touches a few cells
            m = Math.ceil(segL / c);
            var px = ax, py = ay, qx, qy;
            for (t = 1; t <= m; t++) {
                qx = ax + (bx - ax) * t / m; qy = ay + (by - ay) * t / m;
                this.addSeg(id, px, py, qx, qy);
                px = qx; py = qy;
            }
            continue;
        }
        this.addSeg(id, ax, ay, bx, by);
    }
};
// Does a segment of a line other than "self" pass within tol of (px,py)?
// mode 0: only kept lines count; mode 1: any line that existed before (not a duplicate)
LDC_SegGrid.prototype.touches = function (px, py, tol, self, verdict, mode) {
    var cx = Math.floor(px / this.cell), cy = Math.floor(py / this.cell), i, j, arr, q, id, v;
    for (i = -1; i <= 1; i++) for (j = -1; j <= 1; j++) {
        arr = this.map[(cx + i) + "_" + (cy + j)]; if (!arr) continue;
        for (q = 0; q < arr.length; q += 5) {
            id = arr[q];
            if (id === self) continue;
            v = verdict[id];
            if (mode === 0 ? v !== "keep" : v === "dup") continue;
            if (LDC_segDist(px, py, arr[q+1], arr[q+2], arr[q+3], arr[q+4]) <= tol) return true;
        }
    }
    return false;
};
function LDC_segDist(px, py, ax, ay, bx, by) {
    var dx = bx - ax, dy = by - ay, L2 = dx*dx + dy*dy, t = 0;
    if (L2 > 0) { t = ((px - ax) * dx + (py - ay) * dy) / L2; if (t < 0) t = 0; else if (t > 1) t = 1; }
    return LDC_dist(px, py, ax + t * dx, ay + t * dy);
}

// Remove short kept pieces left dangling by the removals: an end that touched a removed
// line before and touches no kept line now. Repeats until nothing changes.
function LDC_orphans(info, verdict, S, chains, progress) {
    var sg = new LDC_SegGrid(Math.max(0.2, S.touchTol * 4)), k, e, changed = true, pass = 0, n = info.length, c;
    // Only pieces no longer than orphanMaxLength can ever qualify (the kept run includes the piece itself)
    var cand = [], only = {}, cx, cy, di, dj, pp;
    for (k = 0; k < n; k++) {
        if (info[k].len > S.orphanMaxLength || verdict[k] !== "keep" || info[k].locked || info[k].pts.length < 4) continue;
        cand.push(k);
        pp = info[k].pts;
        for (e = 0; e < 2; e++) {   // the cells around each candidate end are the only ones ever queried
            cx = Math.floor((e === 0 ? pp[0] : pp[pp.length-2]) / sg.cell); cy = Math.floor((e === 0 ? pp[1] : pp[pp.length-1]) / sg.cell);
            for (di = -1; di <= 1; di++) for (dj = -1; dj <= 1; dj++) only[(cx + di) + "_" + (cy + dj)] = true;
        }
    }
    if (cand.length === 0) return;
    sg.only = only;
    for (k = 0; k < n; k++) {
        if (verdict[k] !== "dup") sg.addPath(k, info[k].pts);
        if (progress && k % 2000 === 0) progress("Finding leftover fragments: indexing", k, n);
    }
    while (changed && pass < 10) {
        changed = false; pass++;
        for (c = 0; c < cand.length; c++) {
            k = cand[c];
            if (progress && c % 1000 === 0) progress("Finding leftover fragments: pass " + pass, c, cand.length);
            if (verdict[k] !== "keep" || info[k].locked || info[k].pts.length < 4) continue;
            var aliveLen = info[k].len;
            if (chains && info[k].chain !== undefined) {
                // only the unbroken run of kept pieces this piece belongs to
                var mem = chains[info[k].chain].members, pos = 0, t;
                for (t = 0; t < mem.length; t++) if (mem[t] === k) pos = t;
                for (t = pos - 1; t >= 0 && verdict[mem[t]] === "keep"; t--) aliveLen += info[mem[t]].len;
                for (t = pos + 1; t < mem.length && verdict[mem[t]] === "keep"; t++) aliveLen += info[mem[t]].len;
            }
            if (aliveLen > S.orphanMaxLength) continue;
            var p = info[k].pts, dangling = false;
            for (e = 0; e < 2; e++) {
                var ex = e === 0 ? p[0] : p[p.length-2], ey = e === 0 ? p[1] : p[p.length-1];
                if (sg.touches(ex, ey, S.touchTol, k, verdict, 0)) continue;                    // still touches a kept line
                if (sg.touches(ex, ey, S.touchTol, k, verdict, 1)) { dangling = true; break; }  // used to touch a removed one
            }
            if (dangling) { verdict[k] = "orphan"; changed = true; }
        }
    }
}

function LDC_run(paths, S, progress) {
    var i, n = paths.length, verdict = [], info = [], cosTol = Math.cos(S.angleTolDeg * Math.PI / 180);
    // 1. Flatten
    for (i = 0; i < n; i++) {
        var pts = LDC_flatten(paths[i].pp, paths[i].closed, S.flattenStep);
        info.push({ i: i, pts: pts, len: LDC_length(pts), layer: paths[i].layer, locked: !!paths[i].locked });
        verdict.push("keep");
        if (progress && i % 2000 === 0) progress("Preparing geometry", i, n);
    }
    // 2. Exact duplicates: keep one per group (unlocked loses to locked; otherwise the first one)
    if (S.removeDuplicates) {
        var groups = {}, key, g;
        for (i = 0; i < n; i++) {
            key = LDC_key(info[i].pts, S.dupDecimals);
            if (!groups[key]) groups[key] = [];
            groups[key].push(info[i]);
            if (progress && i % 2000 === 0) progress("Finding duplicates", i, n);
        }
        for (key in groups) {
            g = groups[key];
            if (g.length < 2) continue;
            g.sort(function (a, b) {
                if (a.locked !== b.locked) return a.locked ? -1 : 1;
                return a.i - b.i;
            });
            for (var j = 1; j < g.length; j++) if (!g[j].locked) verdict[g[j].i] = "dup";
        }
        groups = null;
    }
    // 3. Near-parallel lines: greedy, longest continuous line first
    var order = [], active = [];
    for (i = 0; i < n; i++) { active.push(verdict[i] === "keep"); if (verdict[i] === "keep") order.push(info[i]); }
    var chains = null;
    if (progress) progress("Joining line pieces", 0, n);
    if (S.useChains) chains = LDC_chain(info, active, S, progress);
    else for (i = 0; i < n; i++) { info[i].chain = i; info[i].chainLen = info[i].len; }
    order.sort(function (a, b) {
        if (a.locked !== b.locked) return a.locked ? -1 : 1;
        if (a.chainLen !== b.chainLen) return b.chainLen - a.chainLen;
        if (a.chain !== b.chain) return a.chain - b.chain;
        return b.len - a.len;
    });
    var grid = new LDC_Grid(Math.max(S.nearDist, S.stubDist)), o, smp, cov;
    var stubCandidates = [];
    for (i = 0; i < order.length; i++) {
        o = order[i];
        if (progress && i % 250 === 0) progress("Comparing lines", i, order.length);
        smp = LDC_sample(o.pts, S.sampleStep);
        if (!o.locked && S.removeNearParallel) {
            cov = LDC_coverage(grid, smp, S.nearDist, cosTol, true, S.nearCoverage);
            if (cov >= S.nearCoverage) { verdict[o.i] = "near"; continue; }
        }
        if (!o.locked && S.removeStubs && o.chainLen <= S.stubMaxLength) { o.smp = smp; stubCandidates.push(o); continue; }
        grid.add(smp);
    }
    // 4. Stubs: short paths that lie (any direction) almost entirely on kept lines
    for (i = 0; i < stubCandidates.length; i++) {
        o = stubCandidates[i];
        cov = LDC_coverage(grid, o.smp, S.stubDist, 0, false, S.stubCoverage);
        if (cov >= S.stubCoverage) verdict[o.i] = "stub";
        else grid.add(o.smp);
    }
    grid = null;
    // 5. Fragments left dangling by the removals
    if (S.removeOrphans) LDC_orphans(info, verdict, S, chains, progress);
    return verdict;
}

// ===== Illustrator side =====
(function () {
    // ---------------- SETTINGS (distances in points at final size) ----------------
    var SETTINGS = {
        layersToClean: ["origin"],   // only this layer is touched (capitalization ignored)
        removedLayerName: "Removed by LineDensityCleanUp",

        removeDuplicates: true,   // exact copies stacked on top of each other
        dupDecimals: 3,           // two lines count as copies if they match to 0.001 pt

        removeNearParallel: true, // lines running alongside a kept line
        nearDist: 0.40,           // "alongside" = within this distance (pt). Lower = removes less
        angleTolDeg: 12,          // and within this angle
        nearCoverage: 0.90,       // and for at least this share of its length

        useChains: true,          // treat touching pieces of one continuous line as one line
        joinTol: 0.01,
        maxTurnDeg: 20,
        dirBack: 0.15,

        removeOrphans: true,      // short leftovers whose connection was removed
        orphanMaxLength: 0.30,
        touchTol: 0.02,

        removeStubs: false, stubMaxLength: 0.6, stubDist: 0.15, stubCoverage: 0.9,
        flattenStep: 0.05,
        sampleStep: 0.05,

        selectionMargin: 2        // selection mode: also read lines this close (pt) to the selection
    };
    // ------------------------------------------------------------------------------

    if (app.documents.length === 0) { alert("Open the illustration first."); return; }
    var doc = app.activeDocument;
    var t0 = new Date().getTime();
    function secs() { return Math.round((new Date().getTime() - t0) / 100) / 10; }

    // ---- Log file (open it in Notepad while the script runs to see where it is) ----
    var logFile = null;
    try {
        var folder = Folder.desktop;
        try { if (doc.path && doc.path.fsName && doc.path.exists) folder = doc.path; } catch (e0) {}
        logFile = new File(folder.fsName + "/LineDensityCleanUp_log.txt");
        logFile.encoding = "UTF-8";
        logFile.open("w"); logFile.writeln("LineDensityCleanUp log  " + new Date().toString()); logFile.writeln("Document: " + doc.name); logFile.close();
    } catch (e) { logFile = null; }
    function log(msg) {
        if (!logFile) return;
        try { logFile.open("a"); logFile.writeln("[" + secs() + " s] " + msg); logFile.close(); } catch (e) {}
    }

    // ---- Progress palette (optional; the script works without it) ----
    var win = null, bar = null, txt = null, lastLabel = "";
    try {
        win = new Window("palette", "LineDensityCleanUp");
        txt = win.add("statictext", undefined, "Starting...");
        txt.preferredSize = [380, 20];
        bar = win.add("progressbar", undefined, 0, 100);
        bar.preferredSize = [380, 14];
        win.show();
    } catch (e) { win = null; }
    function progress(label, i, n) {
        if (label !== lastLabel) { log(label + " (" + n + ")"); lastLabel = label; }
        else if (i > 0 && n > 0 && i % 2000 === 0) log("   " + label + " " + i + " / " + n);
        if (!win) return;
        try { txt.text = label + "  " + i + " / " + n; bar.value = n ? Math.round(100 * i / n) : 0; win.update(); } catch (e) {}
    }

    function findLayer(container, name) {
        var i, want = String(name).toLowerCase();
        for (i = 0; i < container.layers.length; i++) if (String(container.layers[i].name).toLowerCase() === want) return container.layers[i];
        return null;
    }
    function layerNames(container) {
        var i, out = [];
        for (i = 0; i < container.layers.length; i++) out.push("\"" + container.layers[i].name + "\"");
        return out.join(", ");
    }

    try {
        // ---- Layers: remember lock/visibility, unlock so items can be moved ----
        var targets = [], states = [], i, j;
        for (i = 0; i < SETTINGS.layersToClean.length; i++) {
            var L = findLayer(doc, SETTINGS.layersToClean[i]);
            if (!L) {
                if (win) win.close();
                log("Layer not found: " + SETTINGS.layersToClean[i] + ". Layers in this file: " + layerNames(doc));
                alert("Layer not found: \"" + SETTINGS.layersToClean[i] + "\"\n\nLayers in this file: " + layerNames(doc) +
                      "\n\nRename the layer with the drawing's lines to \"" + SETTINGS.layersToClean[i] + "\" and run the script again.");
                return;
            }
            targets.push(L);
            states.push([L, L.locked, L.visible]);
            L.locked = false; L.visible = true;
        }

        // ---- Selection mode: bounds of the selection ----
        var selMode = false, sb = null;
        try {
            var sel = doc.selection;
            if (sel && sel.length > 0) {
                selMode = true;
                for (i = 0; i < sel.length; i++) {
                    var b = sel[i].geometricBounds; // [left, top, right, bottom]
                    if (!sb) sb = [b[0], b[1], b[2], b[3]];
                    else { sb[0] = Math.min(sb[0], b[0]); sb[1] = Math.max(sb[1], b[1]); sb[2] = Math.max(sb[2], b[2]); sb[3] = Math.min(sb[3], b[3]); }
                }
                var m = SETTINGS.selectionMargin;
                sb = [sb[0] - m, sb[1] + m, sb[2] + m, sb[3] - m];
            }
        } catch (e) { selMode = false; }
        log(selMode ? "Mode: selection only (" + doc.selection.length + " selected)" : "Mode: whole drawing");

        // ---- Collect path items (recursing into groups and sublayers) ----
        var items = [], itemLayer = [], skippedCompound = 0;
        function collect(container, layerName) {
            var k, it;
            for (k = 0; k < container.pageItems.length; k++) {
                it = container.pageItems[k];
                if (it.typename === "PathItem") { items.push(it); itemLayer.push(layerName); }
                else if (it.typename === "GroupItem") collect(it, layerName);
                else if (it.typename === "CompoundPathItem") skippedCompound++;
            }
            if (container.typename === "Layer") for (k = 0; k < container.layers.length; k++) collect(container.layers[k], layerName);
        }
        progress("Listing paths", 0, 0);
        for (i = 0; i < targets.length; i++) collect(targets[i], targets[i].name);
        log("Found " + items.length + " paths");

        // ---- Read geometry ----
        var n = items.length, paths = [], used = [];
        for (i = 0; i < n; i++) {
            var it = items[i], isSel = false, locked = false;
            try { locked = it.locked || it.hidden; } catch (e) { locked = true; }
            if (selMode) {
                try { isSel = it.selected; } catch (e) {}
                if (!isSel) {
                    var gb = it.geometricBounds;   // skip lines far from the selection
                    if (gb[2] < sb[0] || gb[0] > sb[2] || gb[3] > sb[1] || gb[1] < sb[3]) { if (i % 1000 === 0) progress("Reading paths", i, n); continue; }
                    locked = true;                 // nearby but unselected: compare only, never remove
                }
            }
            var pp = [], pts = it.pathPoints, np = pts.length, p;
            for (j = 0; j < np; j++) {
                p = pts[j];
                var an = p.anchor, ld = p.leftDirection, rd = p.rightDirection;
                pp.push(an[0], an[1], ld[0], ld[1], rd[0], rd[1]);   // flat: 6 numbers per point
            }
            paths.push({ layer: itemLayer[i], closed: it.closed, pp: pp, locked: locked });
            used.push(i);
            if (i % 1000 === 0) progress("Reading paths", i, n);
        }
        log("Read " + paths.length + " paths");

        // ---- Run ----
        var verdict = LDC_run(paths, SETTINGS, progress);
        var checkedCount = paths.length;
        paths = null;

        // ---- Move removed items to a hidden layer, one sublayer per reason ----
        var removed = findLayer(doc, SETTINGS.removedLayerName);
        if (!removed) { removed = doc.layers.add(); removed.name = SETTINGS.removedLayerName; }
        removed.locked = false; removed.visible = true;
        var subNames = { dup: "Duplicates", near: "Near-parallel", orphan: "Fragments", stub: "Stubs" };
        var buckets = { dup: [], near: [], orphan: [], stub: [] }, counts = { dup: 0, near: 0, orphan: 0, stub: 0 };
        for (i = 0; i < verdict.length; i++) if (verdict[i] !== "keep") buckets[verdict[i]].push(items[used[i]]);

        function sub(kind) {
            var s = findLayer(removed, subNames[kind]);
            if (!s) { s = removed.layers.add(); s.name = subNames[kind]; }
            s.locked = false; s.visible = true;
            return s;
        }
        // Move one at a time. (v3 tried selecting and grouping each bucket first; in Illustrator the
        // selection stopped at 1000 items, so that step only wasted time. Single moves were fast.)
        var failed = 0, kinds = ["dup", "near", "orphan", "stub"], kk;
        for (kk = 0; kk < kinds.length; kk++) {
            var kind = kinds[kk], arr = buckets[kind];
            if (arr.length === 0) continue;
            var dest = sub(kind);
            progress("Moving " + subNames[kind], 0, arr.length);
            for (i = 0; i < arr.length; i++) {
                try { arr[i].move(dest, ElementPlacement.PLACEATEND); counts[kind]++; }
                catch (e2) { failed++; }
                if (i % 500 === 0) progress("Moving " + subNames[kind], i, arr.length);
            }
            log("   moved " + counts[kind] + " of " + arr.length);
        }
        removed.visible = false;

        // ---- Restore layer states ----
        for (i = 0; i < states.length; i++) { states[i][0].visible = states[i][2]; states[i][0].locked = states[i][1]; }
        if (win) win.close();

        var summary = "LineDensityCleanUp finished in " + Math.round(secs()) + " s\n\n" +
            (selMode ? "Mode: selection only\n" : "Mode: whole drawing\n") +
            "Paths checked: " + checkedCount + "\n" +
            "Duplicates removed: " + counts.dup + "\n" +
            "Near-parallel removed: " + counts.near + "\n" +
            "Fragments removed: " + counts.orphan + "\n" +
            (counts.stub ? "Stubs removed: " + counts.stub + "\n" : "") +
            (failed ? "Could not move: " + failed + "\n" : "") +
            (skippedCompound ? "Compound paths skipped: " + skippedCompound + "\n" : "") +
            "\nRemoved lines are on the hidden layer \"" + SETTINGS.removedLayerName + "\".";
        log(summary.replace(/\n/g, " | "));
        alert(summary);
    } catch (err) {
        log("ERROR: " + err.message + (err.line ? " (line " + err.line + ")" : ""));
        if (win) try { win.close(); } catch (e) {}
        alert("LineDensityCleanUp stopped with an error:\n" + err.message + (err.line ? " (line " + err.line + ")" : "") + "\n\nSee LineDensityCleanUp_log.txt.");
    }
})();
