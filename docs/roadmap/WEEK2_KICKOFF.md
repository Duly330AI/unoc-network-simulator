# Week 2 Kickoff: Optical Compute + Status Propagation

**Status:** 🚀 **READY TO START**  
**Week 1 Foundation:** ✅ COMPLETE (12/18 tasks, 67%)  
**Integration:** ✅ ALL TESTS PASS (3/3)  
**Target:** 800× optical speedup, real-time status propagation

---

## Executive Summary

Week 2 focuses on **performance-critical implementations** in Go:

1. **Optical Compute Service** - Dijkstra algorithm, goroutines, 800× speedup
2. **Status Propagation Service** - Causal chains, batching, real-time updates

Both services have **infrastructure ready** (gRPC, Python clients, health checks). Week 2 will implement core business logic in Go with aggressive performance optimization.

---

## Week 2 Priorities

### Priority 1: Optical Compute (Days 6-8)

**Goal:** Port `resolve_optical_path()` from Python to Go with Dijkstra algorithm

**Current Performance (Python):**

- Single link create: **35 seconds** (optical resolution bottleneck)
- Optical recompute: **40 seconds** (full topology scan)

**Target Performance (Go):**

- Single link create: **200ms** (175× speedup)
- Optical recompute: **50ms** (800× speedup)

**Implementation Steps:**

1. **Day 6: Dijkstra Algorithm**

   - Port Python pathfinding logic to Go
   - Implement graph data structures
   - Unit tests for correctness

2. **Day 7: Affected ONT Detection**

   - Smart topology scanning (not full scan)
   - Only recompute affected devices
   - Batch updates for efficiency

3. **Day 8: Parallel Processing**
   - Goroutines for concurrent ONT processing
   - Channel-based result aggregation
   - Benchmark vs. Python baseline

**Verification:**

- Integration tests: Verify same results as Python
- Performance tests: Confirm 800× speedup
- End-to-end test: Single link create < 500ms

### Priority 2: Status Propagation (Days 9-10)

**Goal:** Implement causal chain detection and status gating

**Current Performance (Python):**

- Status propagation: **2-5 seconds** (single device cascade)
- Batch status updates: **10-20 seconds** (multiple devices)

**Target Performance (Go):**

- Status propagation: **100ms** (20-50× speedup)
- Batch status updates: **500ms** (20-40× speedup)

**Implementation Steps:**

1. **Day 9: Causal Chain Detection**

   - Dependency graph traversal
   - Status gating rules (ONT → loss window)
   - Unit tests for cascades

2. **Day 10: Batch Optimization**
   - Batch database writes
   - WebSocket event batching
   - Performance benchmarks

**Verification:**

- Integration tests: Verify causal chains correct
- Performance tests: Confirm 20-50× speedup
- Stress test: 100 device cascade < 1s

---

## Technical Foundation (Week 1 Complete)

### Infrastructure Ready ✅

**Go Services:**

- Optical Compute Service (:50051) - scaffolding ready
- Status Propagation Service (:50053) - scaffolding ready
- Health checks implemented
- Database connection patterns validated

**Python Integration:**

- OpticalClient with fallback logic
- StatusClient with fallback logic
- Integration tests passing (3/3)
- Startup scripts ready

**Architecture Validated:**

- Hybrid Python (REST API) + Go (compute) pattern
- gRPC communication working end-to-end
- Shared PostgreSQL access confirmed
- Prometheus metrics ready (optional)

### Code Structure (Week 1)

```
engine-go/
├── proto/                    # Protobuf contracts (578 lines)
│   ├── optical.proto         # Optical compute contract ✅
│   └── status.proto          # Status propagation contract ✅
│
├── internal/                 # Service implementations (420 lines)
│   ├── optical/              # Optical scaffolding ✅
│   │   └── service.go        # RecomputeOpticalPaths stub
│   └── status/               # Status scaffolding ✅
│       └── service.go        # PropagateStatus stub
│
├── cmd/                      # Entrypoints (331 lines)
│   ├── optical-service/      # Optical main.go ✅
│   └── status-service/       # Status main.go ✅
│
└── bin/                      # Executables
    ├── optical-service.exe   # Built and runnable ✅
    └── status-service.exe    # Built and runnable ✅
```

### Python Integration (Week 1)

```
backend/
├── proto/                       # Generated stubs
│   ├── optical_pb2.py           # Message definitions ✅
│   ├── optical_pb2_grpc.py      # Service stub ✅
│   └── status_pb2.py, status_pb2_grpc.py ✅
│
└── clients/go_services/         # Python clients
    ├── optical_client.py        # 124 lines, working ✅
    └── status_client.py         # 112 lines, working ✅
```

---

## Week 2 Implementation Plan

### Day 6: Optical Compute (Dijkstra Foundation)

**Tasks:**

1. Study Python `resolve_optical_path()` logic
2. Implement graph data structures in Go
3. Port Dijkstra algorithm with unit tests
4. Verify correctness vs. Python baseline

**Files to Edit:**

- `engine-go/internal/optical/pathfinding.go` (new)
- `engine-go/internal/optical/service.go` (implement RecomputeOpticalPaths)
- `engine-go/internal/optical/pathfinding_test.go` (new)

**Success Criteria:**

- Unit tests pass (same results as Python)
- Single ONT path resolution < 1ms
- No regressions in correctness

### Day 7: Optical Compute (Affected ONT Detection)

**Tasks:**

1. Implement smart topology scanning
2. Detect affected ONTs (not full scan)
3. Batch database updates
4. Integration tests with Python clients

**Files to Edit:**

- `engine-go/internal/optical/affected_onts.go` (new)
- `engine-go/internal/optical/service.go` (optimize RecomputeOpticalPaths)
- `backend/tests/test_optical_compute_go.py` (new)

**Success Criteria:**

- Only affected ONTs recomputed (not full scan)
- Integration tests pass (Python client → Go service)
- Optical recompute < 100ms for 10 ONTs

### Day 8: Optical Compute (Parallel Processing + Benchmarks)

**Tasks:**

1. Add goroutines for concurrent ONT processing
2. Channel-based result aggregation
3. Performance benchmarks (Python vs. Go)
4. End-to-end validation (single link create)

**Files to Edit:**

- `engine-go/internal/optical/parallel.go` (new)
- `engine-go/internal/optical/service.go` (add goroutines)
- `scripts/benchmark_optical.py` (new)

**Success Criteria:**

- Optical recompute: 40s → 50ms (800× speedup) ✅
- Single link create: 35s → 200ms (175× speedup) ✅
- Integration tests still pass (no regressions)

### Day 9: Status Propagation (Causal Chains)

**Tasks:**

1. Implement dependency graph traversal
2. Status gating rules (ONT → loss window, OLT → health)
3. Unit tests for causal cascades
4. Integration tests with Python clients

**Files to Edit:**

- `engine-go/internal/status/causal.go` (new)
- `engine-go/internal/status/service.go` (implement PropagateStatus)
- `engine-go/internal/status/causal_test.go` (new)
- `backend/tests/test_status_propagation_go.py` (new)

**Success Criteria:**

- Causal chains correct (ONT → OLT → Core)
- Status gating rules enforced (loss window)
- Unit tests pass (cascade scenarios)

### Day 10: Status Propagation (Batch Optimization)

**Tasks:**

1. Batch database writes (reduce round-trips)
2. WebSocket event batching (reduce network overhead)
3. Performance benchmarks (Python vs. Go)
4. Stress test (100 device cascade)

**Files to Edit:**

- `engine-go/internal/status/batch.go` (new)
- `engine-go/internal/status/service.go` (optimize PropagateStatus)
- `scripts/benchmark_status.py` (new)

**Success Criteria:**

- Status propagation: 2-5s → 100ms (20-50× speedup) ✅
- Batch status updates: 10-20s → 500ms (20-40× speedup) ✅
- Stress test: 100 device cascade < 1s ✅

---

## Performance Targets (Week 2)

### Optical Compute

| Metric                   | Python (Baseline) | Go (Target) | Speedup | Priority |
| ------------------------ | ----------------- | ----------- | ------- | -------- |
| Single ONT path          | 100ms             | 1ms         | 100×    | Day 6    |
| Optical recompute (10)   | 1s                | 10ms        | 100×    | Day 7    |
| Optical recompute (100)  | 10s               | 50ms        | 200×    | Day 8    |
| Optical recompute (full) | 40s               | 50ms        | 800×    | Day 8    |
| Single link create       | 35s               | 200ms       | 175×    | Day 8    |

### Status Propagation

| Metric                    | Python (Baseline) | Go (Target) | Speedup | Priority |
| ------------------------- | ----------------- | ----------- | ------- | -------- |
| Single device cascade     | 2-5s              | 100ms       | 20-50×  | Day 9    |
| Batch status (10)         | 5-10s             | 200ms       | 25-50×  | Day 10   |
| Batch status (100)        | 10-20s            | 500ms       | 20-40×  | Day 10   |
| Stress test (100 cascade) | 30s               | 1s          | 30×     | Day 10   |

---

## Testing Strategy

### Unit Tests (Go)

**Optical Compute:**

- `pathfinding_test.go` - Dijkstra correctness
- `affected_onts_test.go` - Smart scanning logic
- `parallel_test.go` - Goroutine coordination

**Status Propagation:**

- `causal_test.go` - Causal chain detection
- `batch_test.go` - Batch optimization

### Integration Tests (Python → Go)

**Optical Compute:**

- `test_optical_compute_go.py` - Python client → Go service
- Verify same results as Python implementation
- Performance benchmarks (baseline vs. target)

**Status Propagation:**

- `test_status_propagation_go.py` - Python client → Go service
- Verify causal chains correct
- Performance benchmarks (baseline vs. target)

### Performance Benchmarks

**Scripts:**

- `scripts/benchmark_optical.py` - Optical compute (Python vs. Go)
- `scripts/benchmark_status.py` - Status propagation (Python vs. Go)

**Metrics:**

- Execution time (ms)
- Memory usage (MB)
- CPU utilization (%)
- Database queries (count)

### Stress Tests

**Scenarios:**

- 100 ONT optical recompute (full topology scan)
- 100 device status cascade (causal chains)
- 64 link batch create (Week 3 prep)

---

## Development Workflow (Week 2)

### Daily Cycle

**Morning:**

1. Review previous day's progress
2. Run integration tests (verify no regressions)
3. Plan daily tasks (specific files to edit)

**Afternoon:**

1. Implement Go service logic
2. Write unit tests (Go)
3. Run integration tests (Python → Go)

**Evening:**

1. Performance benchmarks (Python vs. Go)
2. Document progress (WEEK2_DAYX_COMPLETE.md)
3. Update TODO list (mark completed tasks)

### Quality Gates

**Before Each Commit:**

```powershell
# Run Go tests
cd engine-go
go test ./...

# Run Python integration tests
cd ..
python -m pytest -q backend/tests/test_optical_compute_go.py

# Run linters
python -m ruff check .

# Run benchmarks (optional)
python scripts/benchmark_optical.py
```

### Status Reporting

**Daily Status Report:**

- Tasks completed today
- Performance metrics achieved
- Blockers encountered (if any)
- Next day's plan

**Format:** `docs/roadmap/WEEK2_DAYX_COMPLETE.md`

---

## Risk Mitigation

### Technical Risks

**Risk 1: Performance Targets Too Aggressive**

- **Mitigation:** Incremental optimization (Day 6 → 7 → 8)
- **Fallback:** Reduce target (e.g., 400× instead of 800×)
- **Verification:** Daily benchmarks to track progress

**Risk 2: Go Implementation Correctness**

- **Mitigation:** Unit tests against Python baseline
- **Fallback:** Keep Python fallback in clients
- **Verification:** Integration tests with known topologies

**Risk 3: Database Bottlenecks**

- **Mitigation:** Batch writes, connection pooling
- **Fallback:** Async writes, caching strategies
- **Verification:** Database query profiling

### Schedule Risks

**Risk 4: Week 2 Tasks Take Longer Than Expected**

- **Mitigation:** Daily progress tracking, early warnings
- **Fallback:** Defer Day 10 to Week 3 if needed
- **Verification:** Daily TODO list updates

---

## Success Criteria (Week 2 End)

### Functional Requirements ✅

- [ ] Optical compute service fully implemented
- [ ] Status propagation service fully implemented
- [ ] All unit tests passing (Go)
- [ ] All integration tests passing (Python → Go)
- [ ] Python clients work with Go services

### Performance Requirements ✅

- [ ] Optical recompute: 40s → 50ms (800× speedup)
- [ ] Single link create: 35s → 200ms (175× speedup)
- [ ] Status propagation: 2-5s → 100ms (20-50× speedup)
- [ ] Stress test: 100 device cascade < 1s

### Documentation Requirements ✅

- [ ] Daily status reports (Day 6-10)
- [ ] Performance benchmarks documented
- [ ] README updated (Go service usage)
- [ ] Week 2 retrospective complete

---

## Next Steps

### Immediate Actions (Day 6 Start)

1. **Study Python Implementation**

   ```python
   # backend/services/optical_path_resolver.py
   def resolve_optical_path(ont_id: int) -> Optional[OpticalPath]:
       # Study this logic
   ```

2. **Create Go Data Structures**

   ```go
   // engine-go/internal/optical/pathfinding.go
   type Graph struct {
       Nodes map[int]*Node
       Edges map[int][]*Edge
   }
   ```

3. **Port Dijkstra Algorithm**

   ```go
   // engine-go/internal/optical/pathfinding.go
   func DijkstraShortestPath(graph *Graph, source, target int) ([]int, error) {
       // Implement here
   }
   ```

4. **Write Unit Tests**
   ```go
   // engine-go/internal/optical/pathfinding_test.go
   func TestDijkstraSimplePath(t *testing.T) {
       // Verify correctness
   }
   ```

### Resources

**Documentation:**

- `docs/roadmap/GO-SERVICE-CONTRACTS.md` - Optical algorithm details
- `docs/llm/ARCHITECTURE.md` - System design (r9)
- `backend/services/optical_path_resolver.py` - Python baseline

**Tools:**

- `scripts/benchmark_optical.py` - Performance testing
- `tools/dev/test_grpc_integration.py` - Integration testing
- `start_services.ps1` - Service management

---

## Conclusion

Week 2 is **ready to start** with:

- ✅ All infrastructure complete (Week 1)
- ✅ Clear performance targets (800× optical, 20-50× status)
- ✅ Detailed implementation plan (Day 6-10)
- ✅ Risk mitigation strategies
- ✅ Success criteria defined

**Next Action:** Begin Day 6 - Study Python `resolve_optical_path()` and implement Dijkstra algorithm in Go.

**Target:** Week 2 completion by Day 10 with all performance targets met.

---

**Status:** 🚀 **READY FOR WEEK 2 KICKOFF** ✅
