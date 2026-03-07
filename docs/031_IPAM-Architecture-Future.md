# 031. IPAM Architecture Future

Date: 2026-03-07
Status: Future Design / Architecture Exploration
Context: Scaling beyond single-role static prefixes and preparing multi-region operations.

## 1. Executive Summary

This document evaluates three scalable IPAM evolution paths:
1. Approach A: Multi-region static prefixes (simple evolution)
2. Approach B: Hierarchical prefixes (recommended for telco-grade deployments)
3. Approach C: Dynamic pool expansion (auto-create prefixes on utilization threshold)

Key lesson:
- Single static `/24` per role does not scale for large deployments.
- Increasing one role pool (for example ONT to `/16`) solves short-term exhaustion but not regional or hierarchical segmentation.

## 2. Current Baseline (Static Prefixes)

Current model characteristics:
- One prefix per role (flat model).
- Device type -> pool key mapping is deterministic.
- Allocation scans next free host in prefix.
- Exhaustion yields `POOL_EXHAUSTED`.

Typical role pools in baseline:
- `core_mgmt`, `olt_mgmt`, `aon_mgmt`, `ont_mgmt`, `cpe_mgmt`, `noc_tools`.

Current limitations:
1. No region/site hierarchy.
2. No automatic expansion when a role pool reaches limit.
3. No first-class reclamation workflow for deleted/deprovisioned devices.

## 3. Approach A: Multi-Region Static Prefixes

Goal:
- Keep simple role model, add region dimension.

## 3.1 Model changes
- Add optional `region` attribute to Prefix and Device.
- Prefix lookup prefers `(role, region)` then falls back to legacy `(role, null-region)`.

## 3.2 Provisioning behavior
- Device with region gets region-specific pool.
- Devices without region remain backward-compatible using default role pool.

## 3.3 Pros and cons
Pros:
- Low migration risk.
- Fast implementation.
- Good for early multi-region expansion.

Cons:
- Still flat inside each region.
- Expansion still manual unless combined with Approach C.

## 4. Approach B: Hierarchical IPAM (Recommended for Real ISP)

Goal:
- Align with operational topology: `Region -> Site -> POP -> Device`.

## 4.1 Model changes
- Introduce `Location` hierarchy.
- Assign prefixes to location nodes.
- Devices bind to location.
- Prefix selection walks up location ancestry for best match.

## 4.2 Allocation behavior
- Prefer most specific prefix (POP > Site > Region).
- Optional automatic carving of child prefixes from parent supernet.

## 4.3 Pros and cons
Pros:
- Matches telco operations and reporting.
- Better segmentation and governance.
- Natural fit for geo redundancy and planning.

Cons:
- Highest complexity and migration effort.
- Requires strict prefix planning to avoid fragmentation/overlap.

## 5. Approach C: Dynamic Pool Expansion

Goal:
- Auto-create new blocks (for example `/24`) from a reserved supernet when utilization exceeds threshold.

## 5.1 Behavior
- Compute utilization across role prefixes.
- If threshold exceeded, carve next available subnet.
- Create Prefix record and allocate from new block.

## 5.2 Risks
- Concurrent expansion race conditions.
- Prefix fragmentation over time.
- Requires strong overlap/supernet guardrails.

## 6. Comparison Matrix

| Criterion | Approach A | Approach B | Approach C |
| --- | --- | --- | --- |
| Implementation complexity | Low | High | Medium |
| Multi-region support | Yes | Yes | Indirect |
| Hierarchy support | No | Yes | No |
| Manual intervention | Medium | Medium | Low |
| Migration ease | High | Low | High |
| Telco best-practice fit | Medium | High | Low-Medium |

## 7. Recommendation for UNOC

Phase 1:
- Keep current baseline with corrected capacities and robust observability.

Phase 2:
- Implement Approach A (region-aware role pools) as first scaling step.

Phase 3:
- Implement Approach B if multi-site/multi-datacenter complexity requires it.

Phase 4:
- Add Approach C selectively for zero-touch expansion where operationally acceptable.

## 8. Migration Path (Current -> Multi-Region)

Step 1: Schema extension (no downtime)
- add optional `region` columns
- add indexes for region lookups

Step 2: Backfill strategy
- keep existing rows with null-region as default/legacy
- optionally map devices to regions using deterministic migration rules

Step 3: Seed updates
- allow seeding for explicit region list
- preserve backward-compatible default mode

Step 4: Provisioning updates
- region-aware prefix selection with fallback

Step 5: Validation
- integration tests for region-aware provisioning
- pool utilization checks by region

## 9. Industry Alignment Notes

Relevant standards/patterns:
- RFC 1918 private space planning
- CIDR allocation discipline
- hierarchical allocation for telecom operations
- prefix tagging for role/service/redundancy metadata

## 10. Action Items

Immediate:
- Track future IPAM architecture decisions in roadmap tasks.
- Keep baseline stable and measurable.

Short-term:
- Build Approach A PoC and migration-safe schema path.
- Add region-specific provisioning tests.

Long-term:
- Evaluate Approach B by deployment complexity thresholds.
- Add reclamation and utilization alerting.
- Evaluate external IPAM sync (for example NetBox) when operations require it.
