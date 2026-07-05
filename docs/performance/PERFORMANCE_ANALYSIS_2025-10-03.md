# Performance Analysis & Optimization Recommendations

**Date:** October 3, 2025  
**Tested Scale:** 100-200 devices  
**Target Scale:** 1,000 devices (immediate), 10,000+ devices (future)  
**Testing Method:** Realistic concurrent load (traffic + status + API + provisioning)

---

## Executive Summary

**Critical Finding:** Python backend experiences **exponential performance degradation** at scale:

- **100 devices:** Traffic tick 1.15s, Status 400ms - Acceptable
- **200 devices:** Traffic tick 5.27s, Status 2.46s - **System overload**
- **Degradation:** 4.6x slower traffic, 6.1x slower status (2x devices)

**Root Cause:** O(n²) complexity from:

1. Graph rebuilt on every tick (not cached)
2. N+1 query problem (13,490 DB calls per tick)
3. Lazy loading in hot paths

**Recommendation:** **Option A - Python Optimization** (expected 10x speedup, 1-2 weeks)

- Can reach 1k devices with targeted fixes
- Cheaper and faster than Go migration
- Allows incremental improvement

---

## Table of Contents

1. [Test Methodology](#test-methodology)
2. [Performance Results](#performance-results)
3. [Profiling Analysis](#profiling-analysis)
4. [Bottleneck Details](#bottleneck-details)
5. [Optimization Options](#optimization-options)
6. [Implementation Plan](#implementation-plan)
7. [Expected Outcomes](#expected-outcomes)

---

## Test Methodology

### Realistic Load Test Design

**Why realistic testing?**
Previous synthetic benchmarks measured operations in isolation. Real production systems have:

- Multiple processes competing for DB locks
- Concurrent transactions causing rollbacks
- Cache invalidation from simultaneous updates
- Network latency and connection pooling

**Test Setup:**

- 4 concurrent background workers (threads):
  1. **Traffic Engine:** `TrafficEngine().run_tick()` every 5 seconds
  2. **Status Recompute:** `recompute_dirty(50 devices)` every 2 seconds
  3. **API Queries:** `select(Device/Link)` every 1 second
  4. **Provisioning:** `provision_device(10 devices)` every 10 seconds

**Metrics Collected:**

- avg, min, max, p50, p95, p99 latencies
- Success/error counts
- Database query counts (via profiling)
- Thread contention indicators

**Test Duration:**

- 100 devices: 5 minutes (300s)
- 200 devices: 2 minutes (120s)

---

## Performance Results

### 100 Devices (Baseline)

```
Topology Creation: 0.38s

Traffic Tick:
  Count:  60
  Avg:    1147ms
  p95:    1430ms
  Max:    1606ms

Status Recompute:
  Count:  150
  Avg:    400ms
  p95:    2093ms (spikes!)
  Max:    2154ms

API Queries:
  Avg:    5.57ms
  p95:    7.16ms
  ✅ FAST

Provisioning:
  Avg:    565ms
  ⚠️ Acceptable
```

**Assessment:**

- ❌ Traffic tick 1.15s = **23% of 5s cycle** - Critical bottleneck
- ⚠️ Status spikes to 2.1s - Concerning but manageable
- ✅ API queries fast (<10ms)

### 200 Devices (Breaking Point)

```
Topology Creation: 0.56s (still fast)

Traffic Tick:
  Count:  22
  Avg:    5269ms  ❌ 4.6x SLOWER
  p95:    6249ms
  Max:    6253ms
  ❌ EXCEEDS 5s CYCLE TIME!

Status Recompute:
  Count:  46
  Avg:    2457ms  ❌ 6.1x SLOWER
  p95:    5983ms
  Max:    6596ms

API Queries:
  Avg:    12.81ms  (2.3x slower)
  p95:    27.47ms
  Still acceptable

Provisioning:
  Avg:    1003ms  (1.8x slower)
  Becoming slow
```

**Assessment:**

- ❌ **Traffic tick 5.3s > 5s cycle = System cannot keep up!**
- ❌ **Status recompute 2.5s average = Unacceptable**
- ⚠️ **Exponential scaling:** 2x devices = 4-6x slower (not linear)

### Scaling Analysis

| Devices | Traffic Tick | Status Recompute | Scaling Factor  |
| ------- | ------------ | ---------------- | --------------- |
| 100     | 1.15s        | 400ms            | 1x (baseline)   |
| 200     | 5.27s        | 2.46s            | **4.6x / 6.1x** |
| 500     | ~33s (est)   | ~15s (est)       | **~30x** ⚠️     |
| 1000    | ~132s (est)  | ~60s (est)       | **~115x** ❌    |

**Conclusion:** System exhibits **O(n²)** or **O(n log n)** complexity, not O(n).

---

## Profiling Analysis

### Traffic Engine Profiling (200 devices, 5 ticks)

**Total Time:** 18.037 seconds (3.6s per tick)

```
TOP BOTTLENECKS:

1. build_adjacency()              17.986s  (99% of total)
   - Called: 5 times
   - Per call: 3.6 seconds
   - Reason: Rebuilds entire graph on every tick

2. session.get() (lazy loading)   22.091s cumulative
   - Called: 13,490 times
   - Reason: N+1 query problem

3. evaluate_link_status()         13.373s
   - Called: 810 times
   - Reason: Status evaluation in traffic hot path

4. has_upstream_l3_or_anchor()    6.887s
   - Called: 1,000 times
   - Reason: Graph traversal per device

5. Database waits                 8.784s
   - select.select() blocking
   - Connection pool contention
```

### Status Recompute Profiling (200 devices, 1 run)

**Total Time:** 3.471 seconds

```
TOP BOTTLENECKS:

1. _ensure_graph_cache()          1.834s
   - Graph building/caching
   - Still slow even with cache

2. has_upstream_l3_or_anchor()    1.523s
   - Called: 200 times (once per device)
   - Per call: 8ms
   - Graph traversal with lazy loading

3. session.get() (lazy loading)   1.474s
   - Called: 4,172 times
   - N+1 queries again

4. is_link_passable()             1.469s
   - Called: 162 times
   - Lazy loads link endpoints

5. build_logical_graph()          0.220s
   - Called: 187 times
   - Less critical but adds up
```

---

## Bottleneck Details

### 1. `build_adjacency()` - Traffic Engine Death

**Location:** `backend/services/traffic/v2_graph.py:8`

**Problem Code:**

```python
def build_adjacency(ifaces, links, evaluate_link_status, is_link_passable):
    """Build adjacency and mappings for passable links."""
    iface_to_device: dict[str, str] = {i.id: i.device_id for i in ifaces}
    device_neighbors: dict[str, set[str]] = {}
    link_by_pair: dict[frozenset[str], str] = {}

    for ln in links:  # 200 links
        try:
            if not is_link_passable(ln):  # ⚠️ LAZY LOAD + DB QUERY!
                continue
            eff = evaluate_link_status(ln)  # ⚠️ LAZY LOAD + DB QUERY!
            if eff != Status.UP:
                continue
        except Exception:
            if getattr(ln, "status", None) != Status.UP:
                continue

        a_dev = iface_to_device.get(ln.a_interface_id)
        b_dev = iface_to_device.get(ln.b_interface_id)
        if not a_dev or not b_dev:
            continue
        device_neighbors.setdefault(a_dev, set()).add(b_dev)
        device_neighbors.setdefault(b_dev, set()).add(a_dev)
        link_by_pair[frozenset({a_dev, b_dev})] = ln.id

    return device_neighbors, link_by_pair, iface_to_device
```

**Issues:**

1. **Called on EVERY tick** - No caching
2. **`is_link_passable(ln)`** - Loads link endpoints (2 DB queries per link)
3. **`evaluate_link_status(ln)`** - Loads device dependencies (N queries per link)
4. **200 links = 400+ DB queries in a loop**

**Why it's O(n²):**

- For N devices, ~N links
- Each link triggers N/10 queries (dependency checks)
- Total: N × (N/10) = O(n²)

**Fix:**

```python
# 1. Cache the graph result (invalidate on topology changes)
_adjacency_cache = None
_cache_timestamp = None

def build_adjacency_cached(ifaces, links, evaluate_link_status, is_link_passable):
    global _adjacency_cache, _cache_timestamp

    # Check if cache is valid (topology hasn't changed)
    if _adjacency_cache and not _topology_changed_since(_cache_timestamp):
        return _adjacency_cache

    # 2. Eager load all relationships ONCE
    ifaces_with_device = session.exec(
        select(Interface)
        .options(joinedload(Interface.device))
    ).all()

    links_with_endpoints = session.exec(
        select(Link)
        .options(
            joinedload(Link.a_interface).joinedload(Interface.device),
            joinedload(Link.b_interface).joinedload(Interface.device),
        )
    ).all()

    # 3. Pre-compute link status (don't call evaluate_link_status in loop)
    link_status_map = {ln.id: ln.effective_status for ln in links_with_endpoints}

    # 4. Build adjacency (now O(n) with no DB queries)
    iface_to_device = {i.id: i.device_id for i in ifaces_with_device}
    device_neighbors = {}
    link_by_pair = {}

    for ln in links_with_endpoints:
        # Use pre-computed status
        if link_status_map.get(ln.id) != Status.UP:
            continue

        # No DB queries - data already loaded
        a_dev = iface_to_device.get(ln.a_interface_id)
        b_dev = iface_to_device.get(ln.b_interface_id)
        if not a_dev or not b_dev:
            continue

        device_neighbors.setdefault(a_dev, set()).add(b_dev)
        device_neighbors.setdefault(b_dev, set()).add(a_dev)
        link_by_pair[frozenset({a_dev, b_dev})] = ln.id

    # Cache result
    _adjacency_cache = (device_neighbors, link_by_pair, iface_to_device)
    _cache_timestamp = time.time()

    return _adjacency_cache
```

**Expected Improvement:**

- **Before:** 3.6s per tick
- **After:** <50ms per tick (cached), ~200ms on cache miss
- **Speedup:** **72x** on hits, **18x** on misses

---

### 2. N+1 Query Problem - session.get()

**Problem:**

- 13,490 calls to `session.get()` in traffic tick
- 4,172 calls in status recompute
- Each call = 1 DB query

**Why it happens:**
SQLAlchemy lazy-loads relationships by default:

```python
device = session.get(Device, device_id)
device.interfaces  # ⚠️ Triggers query
device.interfaces[0].link_a  # ⚠️ Triggers another query
device.interfaces[0].link_a.b_interface  # ⚠️ And another!
```

**Fix - Eager Loading:**

```python
# BAD - Lazy loading (N+1 queries)
devices = session.exec(select(Device)).all()
for dev in devices:
    for iface in dev.interfaces:  # Query per device
        if iface.link_a:  # Query per interface
            neighbor = iface.link_a.b_interface.device  # More queries!

# GOOD - Eager loading (1 query)
devices = session.exec(
    select(Device)
    .options(
        joinedload(Device.interfaces)
        .joinedload(Interface.link_a)
        .joinedload(Link.b_interface)
        .joinedload(Interface.device)
    )
).all()
# All data loaded in ONE query!
```

**Expected Improvement:**

- **Before:** 13,490 queries = ~5 seconds
- **After:** 10-20 queries = ~50ms
- **Speedup:** **100x**

---

### 3. has_upstream_l3_or_anchor() - O(n²) Graph Traversal

**Location:** `backend/services/dependency_resolver_core.py:202`

**Problem:**

- Called once per device (200 times for 200 devices)
- Each call traverses dependency graph with DB queries
- Total complexity: O(n²)

**Profile:**

```
Traffic:  1,000 calls, 6.887s, ~7ms per call
Status:   200 calls,  1.523s, ~8ms per call
```

**Fix - Cache Graph Traversal Results:**

```python
# Cache traversal results per session
_l3_anchor_cache = {}

def has_upstream_l3_or_anchor(device_id: str) -> bool:
    if device_id in _l3_anchor_cache:
        return _l3_anchor_cache[device_id]

    # Do traversal once
    result = _traverse_to_l3_or_anchor(device_id)

    # Cache result
    _l3_anchor_cache[device_id] = result
    return result

# Clear cache on topology changes
def invalidate_dependency_cache():
    global _l3_anchor_cache
    _l3_anchor_cache = {}
```

**Expected Improvement:**

- **Before:** 1.5s for 200 devices
- **After:** ~50ms for 200 devices (cache hit ratio >95%)
- **Speedup:** **30x**

---

### 4. evaluate_link_status() in Traffic Hot Path

**Problem:**
Status logic is executed INSIDE traffic engine tick loop:

```python
for ln in links:
    eff = evaluate_link_status(ln)  # ⚠️ EXPENSIVE!
    if eff != Status.UP:
        continue
```

**Why it's wrong:**

- Traffic engine should use **cached status**, not compute it
- Status recompute should run separately
- Mixing concerns = double work

**Fix - Use Cached Status:**

```python
# Traffic engine should ONLY read cached status
for ln in links:
    # Use pre-computed effective_status field
    if ln.effective_status != Status.UP:
        continue
    # Continue with traffic logic...
```

**Expected Improvement:**

- **Before:** 13.373s spent on status evaluation in traffic
- **After:** ~10ms to read cached status
- **Speedup:** **1300x** (eliminates redundant work)

---

## Optimization Options

### Option A: Python Optimization (RECOMMENDED)

**Timeline:** 1-2 weeks  
**Cost:** Low (code changes only)  
**Risk:** Low (incremental improvements)

**Optimizations:**

1. **Cache `build_adjacency()` result** [Priority 1]

   - Invalidate only on topology changes (device/link CRUD)
   - Expected: 3.6s → 50ms per tick (**72x faster**)

2. **Eliminate N+1 queries with eager loading** [Priority 1]

   - Add `joinedload()` to all hot path queries
   - Expected: 13,490 queries → 20 queries (**~700x fewer**)

3. **Separate status from traffic** [Priority 1]

   - Traffic reads cached `effective_status` field
   - Expected: 13.373s → 10ms (**1300x faster**)

4. **Cache graph traversal** [Priority 2]

   - Cache `has_upstream_l3_or_anchor()` results
   - Expected: 1.5s → 50ms (**30x faster**)

5. **Bulk load in status recompute** [Priority 2]
   - Batch device loads with single query
   - Expected: 4,172 queries → 10 queries (**~400x fewer**)

**Expected Results:**

```
100 devices:
  Traffic tick: 1150ms → 50ms   (23x faster)
  Status:       400ms → 50ms    (8x faster)

200 devices:
  Traffic tick: 5300ms → 150ms  (35x faster)
  Status:       2500ms → 200ms  (12x faster)

500 devices (projected):
  Traffic tick: ~500ms  ✅ (under 1s target)
  Status:       ~800ms  ✅ (acceptable)

1000 devices (projected):
  Traffic tick: ~1200ms  ⚠️ (close to limit)
  Status:       ~2000ms  ⚠️ (getting slow)
```

**Assessment:**

- ✅ Can reach 1k devices target
- ⚠️ 10k devices would need Go migration
- ✅ Buys time to properly design Go solution

---

### Option B: Go Migration (Complete)

**Timeline:** 4-6 weeks  
**Cost:** High (complete rewrite)  
**Risk:** High (full migration, compatibility issues)

**What gets migrated:**

- Traffic engine → Go
- Status recompute → Go
- Pathfinding → Go
- Dependency resolver → Go
- All entities (Device, Link, Interface, Route, etc.)

**Architecture:**

```
┌─────────────────────────────────────────┐
│         Python FastAPI Backend          │
│  (API, WebSocket, provisioning, DB ORM) │
└────────────┬────────────────────────────┘
             │
             │ gRPC
             ▼
┌─────────────────────────────────────────┐
│           Go Engine Service             │
│  - Traffic engine (in-memory state)     │
│  - Status computation (graph ops)       │
│  - Pathfinding (efficient algorithms)   │
│  - Dependency resolution (cached)       │
└─────────────────────────────────────────┘
```

**Pros:**

- 10-50x performance improvement
- Can scale to 10k+ devices
- Better concurrency (no GIL)
- Lower memory usage

**Cons:**

- 4-6 weeks development time
- Need to maintain two codebases
- gRPC complexity
- Proto definitions for all entities
- Python-Go impedance mismatch

**Expected Results:**

```
1000 devices:
  Traffic tick: ~50-100ms  ✅
  Status:       ~100-200ms ✅

10000 devices:
  Traffic tick: ~500ms  ✅
  Status:       ~1s     ✅
```

**Assessment:**

- ✅ Best long-term solution for 10k+ scale
- ❌ Overkill if 1k devices is sufficient
- ⚠️ Previous attempt failed - need better design

---

### Option C: Hybrid (Traffic to Go, Status in Python)

**Timeline:** 2-3 weeks  
**Cost:** Medium  
**Risk:** Medium

**What gets migrated:**

- Traffic engine ONLY → Go
- Status, provisioning, API stay in Python

**Rationale:**

- Traffic is the critical bottleneck (5.3s vs 2.5s for status)
- Simpler proto (only traffic-related entities)
- Python can handle status optimization

**Architecture:**

```
Python Backend (API, Status, Provisioning)
         │
         │ gRPC - TrafficDelta stream
         ▼
Go Traffic Engine (in-memory tariffs, traffic state)
```

**Pros:**

- Smaller scope than full migration
- Addresses biggest bottleneck
- Simpler proto design
- Faster delivery (2-3 weeks)

**Cons:**

- Still need gRPC infrastructure
- Status remains slow (but acceptable)
- May need Go migration later anyway

**Expected Results:**

```
200 devices:
  Traffic tick: 5300ms → 50ms  (106x faster)
  Status:       2500ms → 500ms (5x faster with partial optimization)

1000 devices:
  Traffic tick: ~200ms  ✅
  Status:       ~2s     ⚠️ (acceptable but not great)
```

**Assessment:**

- ✅ Good compromise
- ✅ Faster than full Go migration
- ⚠️ Status still needs optimization
- ⚠️ May defer full solution

---

## Implementation Plan

### Phase 1: Quick Wins (Week 1)

**Goal:** Get 200 devices working acceptably

1. **Cache `build_adjacency()` result** [2 days]

   - Add cache with topology change invalidation
   - Test: Traffic tick should drop from 5.3s → 1s

2. **Use cached status in traffic** [1 day]

   - Remove `evaluate_link_status()` from traffic loop
   - Use `ln.effective_status` field instead
   - Test: Should eliminate 13s bottleneck

3. **Add eager loading to traffic queries** [2 days]
   - `joinedload(Interface.device)`
   - `joinedload(Link.a_interface, Link.b_interface)`
   - Test: Reduce query count from 13k → 50

**Expected outcome:**

```
200 devices:
  Traffic tick: 5300ms → 500ms  ✅
  Status:       2500ms → 2000ms ⚠️ (minimal change)
```

### Phase 2: Status Optimization (Week 2)

**Goal:** Optimize status recompute

1. **Cache graph traversal** [2 days]

   - Add cache to `has_upstream_l3_or_anchor()`
   - Invalidate on topology changes
   - Test: 1.5s → 50ms

2. **Eager loading in status** [2 days]

   - Batch load devices with all relationships
   - Test: 4k queries → 20 queries

3. **Optimize `is_link_passable()`** [1 day]
   - Pre-load link endpoints
   - Test: 1.5s → 100ms

**Expected outcome:**

```
200 devices:
  Traffic tick: 500ms → 150ms   ✅
  Status:       2000ms → 300ms  ✅
```

### Phase 3: Scale Testing (Week 3)

**Goal:** Validate at 500 and 1000 devices

1. **Test 500 devices** [1 day]

   - Run realistic load test
   - Profile if needed
   - Target: Traffic <1s, Status <1s

2. **Test 1000 devices** [1 day]

   - Run realistic load test
   - Identify remaining bottlenecks
   - Target: Traffic <2s, Status <2s

3. **Additional optimizations** [3 days]
   - Based on profiling results
   - Database indexes
   - Query optimization
   - Connection pooling

**Expected outcome:**

```
1000 devices:
  Traffic tick: ~1200ms  ⚠️ (close to acceptable)
  Status:       ~2000ms  ⚠️ (acceptable)
```

### Phase 4: Decision Point

**If 1000 devices acceptable:**

- ✅ Ship Python optimization
- Monitor production performance
- Plan Go migration for 10k scale later

**If 1000 devices still too slow:**

- Go to Option C (Hybrid - Traffic to Go)
- 2-3 weeks additional work
- Expected: Traffic <200ms, Status <2s

---

## Expected Outcomes

### Performance Improvements (Python Optimization)

| Metric                 | Before | After | Improvement         |
| ---------------------- | ------ | ----- | ------------------- |
| Traffic tick (200 dev) | 5.3s   | 150ms | **35x faster**      |
| Status (200 dev)       | 2.5s   | 300ms | **8x faster**       |
| DB queries (traffic)   | 13,490 | 20    | **675x fewer**      |
| DB queries (status)    | 4,172  | 20    | **209x fewer**      |
| Cache hit ratio        | 0%     | 95%+  | **Massive savings** |

### Scaling Projection

```
Current (no optimization):
  100 devices:  Traffic 1.15s, Status 400ms   ✅
  200 devices:  Traffic 5.27s, Status 2.46s   ❌
  500 devices:  FAILS (estimated 30s+)        ❌
  1000 devices: IMPOSSIBLE                    ❌

After Python optimization:
  100 devices:  Traffic 50ms,   Status 50ms   ✅✅
  200 devices:  Traffic 150ms,  Status 300ms  ✅✅
  500 devices:  Traffic 500ms,  Status 800ms  ✅
  1000 devices: Traffic 1200ms, Status 2000ms ⚠️

With Go migration (Option B):
  1000 devices:  Traffic 50ms,   Status 200ms  ✅✅
  10000 devices: Traffic 500ms,  Status 1000ms ✅
```

---

## Risk Assessment

### Python Optimization (Option A)

**Technical Risks:**

- 🟢 Cache invalidation bugs (mitigated by tests)
- 🟢 Eager loading breaks existing code (mitigated by gradual rollout)
- 🟡 May not reach 1k devices (fallback to hybrid)

**Business Risks:**

- 🟢 Low cost, fast delivery
- 🟢 Incremental improvements
- 🟡 May need Go migration later anyway

**Overall:** ✅ LOW RISK

### Go Migration (Option B)

**Technical Risks:**

- 🔴 Previous attempt failed - need better design
- 🔴 Python-Go impedance mismatch
- 🟡 gRPC debugging complexity
- 🟡 Proto evolution challenges

**Business Risks:**

- 🔴 4-6 weeks = delayed features
- 🔴 Two codebases to maintain
- 🟡 Team needs Go expertise

**Overall:** ⚠️ HIGH RISK (but necessary for 10k scale)

### Hybrid (Option C)

**Technical Risks:**

- 🟡 Still need gRPC infrastructure
- 🟡 Status remains Python (slower)
- 🟡 May need full migration later

**Business Risks:**

- 🟢 2-3 weeks = faster than full Go
- 🟡 Addresses biggest bottleneck only
- 🟡 Partial solution

**Overall:** 🟡 MEDIUM RISK

---

## Recommendation

### Immediate Action: **Option A - Python Optimization**

**Why:**

1. **Proven path:** Clear bottlenecks identified, solutions known
2. **Fast delivery:** 1-2 weeks vs 4-6 weeks for Go
3. **Low risk:** Incremental improvements, easy to test
4. **Sufficient:** Can reach 1k devices target
5. **Buys time:** Allows proper Go design if needed later

**Implementation:**

- Week 1: Quick wins (cache + eager loading)
- Week 2: Status optimization
- Week 3: Scale testing + final tuning

**Success Criteria:**

- ✅ 200 devices: Traffic <500ms, Status <500ms
- ✅ 500 devices: Traffic <1s, Status <1.5s
- ⚠️ 1000 devices: Traffic <2s, Status <3s (acceptable)

**Fallback:**
If 1000 devices still too slow after Python optimization:

- Move to Option C (Hybrid - Traffic to Go)
- Additional 2-3 weeks
- Addresses critical bottleneck only

---

## Next Steps

1. **Get approval** on Option A approach
2. **Create implementation tickets** with detailed specs
3. **Set up monitoring** for production performance tracking
4. **Start Week 1** - Quick wins (cache + eager loading)
5. **Daily standup** to review progress and adjust

---

## Appendix: Profiling Data

### Traffic Engine Profile (200 devices, 5 ticks)

**Artifact:** archived 200-device traffic profile output

```
Total: 18.037 seconds (3.6s per tick)

Top 10 functions:
  1. build_adjacency()         17.986s  (99%)
  2. session.get()             22.091s cumulative
  3. evaluate_link_status()    13.373s
  4. has_upstream_l3_or_anchor() 6.887s
  5. session._execute_internal() 18.532s
  6. Database waits (select.select) 6.376s
  7. load_on_pk_identity()     21.347s
  8. _compute_override_fingerprint() 5.441s
  9. result._fetchall_impl()    3.415s
 10. loading._instance()        2.427s

Total function calls: 15,504,643
Primitive calls: 15,318,903
```

### Status Recompute Profile (200 devices, 1 run)

**Artifact:** archived 200-device status profile output

```
Total: 3.471 seconds

Top 10 functions:
  1. recompute_dirty()          3.488s
  2. _ensure_graph_cache()      1.834s
  3. has_upstream_l3_or_anchor() 1.523s
  4. session._execute_internal() 1.582s
  5. session.get()              1.474s
  6. is_link_passable()         1.469s
  7. _compute_override_fingerprint() 1.105s
  8. Database waits              1.244s
  9. load_on_pk_identity()      1.186s
 10. build_logical_graph()      0.220s

Total function calls: 3,491,122
Primitive calls: 3,461,748
```

---

## Conclusion

The Python backend has clear, identifiable bottlenecks that can be resolved with targeted optimizations. The **Option A - Python Optimization** approach is recommended as the immediate path forward, with a potential hybrid or full Go migration deferred until we validate the 1k device target.

**Key Takeaway:** We don't need to "boil the ocean" - targeted fixes can deliver 10-35x performance improvements in 1-2 weeks, getting us to 1k devices. Go migration can be properly designed and executed later if 10k+ scale is needed.
