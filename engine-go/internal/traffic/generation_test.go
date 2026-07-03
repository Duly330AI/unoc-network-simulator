package traffic

import (
	"database/sql"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/unoc/engine-go/internal/graph"
	"github.com/unoc/engine-go/internal/models"
)

// TestDeterministicRandom_Bounds tests that random values are in [0.8, 1.0] range
func TestDeterministicRandom_Bounds(t *testing.T) {
	testCases := []struct {
		name     string
		seed     int
		tick     int
		deviceID string
	}{
		{"Seed 42, Tick 1", 42, 1, "ont1"},
		{"Seed 0, Tick 0", 0, 0, "ont1"},
		{"Seed 999, Tick 100", 999, 100, "ont_business_42"},
		{"Negative Seed", -123, 50, "device_xyz"},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			result := deterministicRandom(tc.seed, tc.tick, tc.deviceID)

			assert.GreaterOrEqual(t, result, 0.8, "random value should be >= 0.8")
			assert.LessOrEqual(t, result, 1.0, "random value should be <= 1.0")
		})
	}
}

// TestDeterministicRandom_Deterministic tests that same inputs → same outputs
func TestDeterministicRandom_Deterministic(t *testing.T) {
	seed := 42
	tick := 10
	deviceID := "ont_test_123"

	// Generate same random value 5 times
	values := make([]float64, 5)
	for i := 0; i < 5; i++ {
		values[i] = deterministicRandom(seed, tick, deviceID)
	}

	// All values should be identical
	for i := 1; i < len(values); i++ {
		assert.Equal(t, values[0], values[i], "deterministic random should produce identical outputs")
	}
}

// TestDeterministicRandom_DifferentInputs tests that different inputs → different outputs
func TestDeterministicRandom_DifferentInputs(t *testing.T) {
	baseValue := deterministicRandom(42, 10, "ont1")

	// Different seed
	diffSeed := deterministicRandom(99, 10, "ont1")
	assert.NotEqual(t, baseValue, diffSeed, "different seed should produce different value")

	// Different tick
	diffTick := deterministicRandom(42, 99, "ont1")
	assert.NotEqual(t, baseValue, diffTick, "different tick should produce different value")

	// Different device ID
	diffDevice := deterministicRandom(42, 10, "ont2")
	assert.NotEqual(t, baseValue, diffDevice, "different device ID should produce different value")
}

// TestBfsPickAnchor_SimpleTopology tests pathfinding in basic ONT → OLT → Core topology
func TestBfsPickAnchor_SimpleTopology(t *testing.T) {
	// Arrange: ONT → OLT → Core (Core is anchor)
	devices := []models.Device{
		{ID: "core1", Type: models.DeviceTypeCoreRouter, Status: "UP"},
		{ID: "olt1", Type: models.DeviceTypeOLT, Status: "UP"},
		{ID: "ont1", Type: models.DeviceTypeBusinessONT, Status: "UP"},
	}

	links := []models.Link{
		{ID: "link1", AInterfaceID: "ont1-eth0", BInterfaceID: "olt1-eth0", Status: "UP"},
		{ID: "link2", AInterfaceID: "olt1-eth1", BInterfaceID: "core1-eth0", Status: "UP"},
	}

	cache := buildTestCache(devices, links)
	adj := buildTestAdjacency(cache, links)

	anchorTypes := map[models.DeviceType]bool{
		models.DeviceTypeCoreRouter: true,
	}

	// Act
	pathNodes, pathLinks := bfsPickAnchor("ont1", adj, cache, anchorTypes)

	// Assert: Path should be [ont1, olt1, core1]
	assert.Len(t, pathNodes, 3, "path should have 3 nodes (ont1 → olt1 → core1)")
	assert.Equal(t, "ont1", pathNodes[0], "path should start at ont1")
	assert.Equal(t, "olt1", pathNodes[1], "path should go through olt1")
	assert.Equal(t, "core1", pathNodes[2], "path should end at core1")
	assert.Len(t, pathLinks, 2, "path should have 2 links")
	assert.Equal(t, "link1", pathLinks[0], "first link should be link1")
	assert.Equal(t, "link2", pathLinks[1], "second link should be link2")
}

// TestBfsPickAnchor_MultihopPath tests pathfinding through multiple hops
func TestBfsPickAnchor_MultihopPath(t *testing.T) {
	// Arrange: ONT → OLT → EdgeRouter → Core (4-hop path to anchor)
	devices := []models.Device{
		{ID: "core1", Type: models.DeviceTypeCoreRouter, Status: "UP"},
		{ID: "edge1", Type: models.DeviceTypeEdgeRouter, Status: "UP"},
		{ID: "olt1", Type: models.DeviceTypeOLT, Status: "UP"},
		{ID: "ont1", Type: models.DeviceTypeBusinessONT, Status: "UP"},
	}

	links := []models.Link{
		{ID: "link1", AInterfaceID: "ont1-eth0", BInterfaceID: "olt1-eth0", Status: "UP"},
		{ID: "link2", AInterfaceID: "olt1-eth1", BInterfaceID: "edge1-eth0", Status: "UP"},
		{ID: "link3", AInterfaceID: "edge1-eth1", BInterfaceID: "core1-eth0", Status: "UP"},
	}

	cache := buildTestCache(devices, links)
	adj := buildTestAdjacency(cache, links)

	anchorTypes := map[models.DeviceType]bool{
		models.DeviceTypeCoreRouter: true,
	}

	// Act
	pathNodes, pathLinks := bfsPickAnchor("ont1", adj, cache, anchorTypes)

	// Assert: Path should be [ont1, olt1, edge1, core1]
	assert.Len(t, pathNodes, 4, "path should have 4 nodes (ont1 → olt1 → edge1 → core1)")
	assert.Equal(t, "ont1", pathNodes[0], "path should start at ont1")
	assert.Equal(t, "olt1", pathNodes[1], "path should go through olt1")
	assert.Equal(t, "edge1", pathNodes[2], "path should go through edge1")
	assert.Equal(t, "core1", pathNodes[3], "path should end at core1")
	assert.Len(t, pathLinks, 3, "path should have 3 links")
}

// TestBfsPickAnchor_NoAnchorReachable tests behavior when no anchor is reachable
func TestBfsPickAnchor_NoAnchorReachable(t *testing.T) {
	// Arrange: ONT isolated (no anchor reachable)
	devices := []models.Device{
		{ID: "ont1", Type: models.DeviceTypeBusinessONT, Status: "UP"},
	}

	cache := buildTestCache(devices, []models.Link{})
	adj := buildTestAdjacency(cache, []models.Link{})

	anchorTypes := map[models.DeviceType]bool{
		models.DeviceTypeCoreRouter: true,
	}

	// Act
	pathNodes, pathLinks := bfsPickAnchor("ont1", adj, cache, anchorTypes)

	// Assert: Should return only the leaf device
	assert.Len(t, pathNodes, 1, "isolated device should have path of length 1")
	assert.Equal(t, "ont1", pathNodes[0], "path should only contain ont1")
	assert.Len(t, pathLinks, 0, "isolated device should have no links in path")
}

// TestBfsPickAnchor_SkipDownDevices tests that BFS skips DOWN devices
func TestBfsPickAnchor_SkipDownDevices(t *testing.T) {
	// Arrange: ONT → OLT (DOWN) → Core (should skip OLT)
	devices := []models.Device{
		{ID: "core1", Type: models.DeviceTypeCoreRouter, Status: "UP"},
		{ID: "olt1", Type: models.DeviceTypeOLT, Status: "DOWN"}, // OLT is DOWN
		{ID: "ont1", Type: models.DeviceTypeBusinessONT, Status: "UP"},
	}

	links := []models.Link{
		{ID: "link1", AInterfaceID: "ont1-eth0", BInterfaceID: "olt1-eth0", Status: "UP"},
		{ID: "link2", AInterfaceID: "olt1-eth1", BInterfaceID: "core1-eth0", Status: "UP"},
	}

	cache := buildTestCache(devices, links)
	adj := buildTestAdjacency(cache, links)

	anchorTypes := map[models.DeviceType]bool{
		models.DeviceTypeCoreRouter: true,
	}

	// Act
	pathNodes, pathLinks := bfsPickAnchor("ont1", adj, cache, anchorTypes)

	// Assert: No path should be found (OLT is DOWN, blocking path to core)
	assert.Len(t, pathNodes, 1, "should not traverse through DOWN devices")
	assert.Equal(t, "ont1", pathNodes[0], "should only return leaf device")
	assert.Len(t, pathLinks, 0, "should have no links when path is blocked")
}

// TestGenerateFlows_BasicGeneration tests traffic generation for a single ONT
func TestGenerateFlows_BasicGeneration(t *testing.T) {
	// Arrange: ONT → OLT → Core with tariff
	devices := []models.Device{
		{
			ID:          "core1",
			Type:        models.DeviceTypeCoreRouter,
			Status:      "UP",
			Provisioned: true,
		},
		{
			ID:          "olt1",
			Type:        models.DeviceTypeOLT,
			Status:      "UP",
			Provisioned: true,
		},
		{
			ID:          "ont1",
			Type:        models.DeviceTypeBusinessONT,
			Status:      "UP",
			Provisioned: true,
			TariffID:    sql.NullInt64{Int64: 1, Valid: true},
		},
	}

	links := []models.Link{
		{ID: "link1", AInterfaceID: "ont1-eth0", BInterfaceID: "olt1-eth0", Status: "UP"},
		{ID: "link2", AInterfaceID: "olt1-eth1", BInterfaceID: "core1-eth0", Status: "UP"},
	}

	tariffs := []models.Tariff{
		{ID: 1, MaxUpMbps: 100.0, MaxDownMbps: 500.0},
	}

	cache := buildTestCacheWithTariffs(devices, links, tariffs)
	adj := buildTestAdjacency(cache, links)

	// Act
	result := GenerateFlows(cache, adj, 1, 42)

	// Assert
	assert.Equal(t, 1, result.LeavesCount, "should process 1 leaf device")
	assert.Len(t, result.DeviceMetrics, 3, "should have metrics for 3 devices (ont1, olt1, core1)")
	assert.Len(t, result.LinkMetrics, 2, "should have metrics for 2 links")

	// Check traffic bounds (80-100% of tariff)
	ontMetrics := result.DeviceMetrics["ont1"]
	assert.NotNil(t, ontMetrics, "ont1 should have metrics")
	assert.GreaterOrEqual(t, ontMetrics.UpBps, 80e6, "up traffic should be >= 80 Mbps")
	assert.LessOrEqual(t, ontMetrics.UpBps, 100e6, "up traffic should be <= 100 Mbps")
	assert.GreaterOrEqual(t, ontMetrics.DownBps, 400e6, "down traffic should be >= 400 Mbps")
	assert.LessOrEqual(t, ontMetrics.DownBps, 500e6, "down traffic should be <= 500 Mbps")

	// Check aggregation (OLT and Core should have same traffic as ONT)
	oltMetrics := result.DeviceMetrics["olt1"]
	assert.NotNil(t, oltMetrics, "olt1 should have metrics")
	assert.Equal(t, ontMetrics.UpBps, oltMetrics.UpBps, "olt1 should aggregate ont1 traffic")
	assert.Equal(t, ontMetrics.DownBps, oltMetrics.DownBps, "olt1 should aggregate ont1 traffic")

	coreMetrics := result.DeviceMetrics["core1"]
	assert.NotNil(t, coreMetrics, "core1 should have metrics")
	assert.Equal(t, ontMetrics.UpBps, coreMetrics.UpBps, "core1 should aggregate ont1 traffic")
	assert.Equal(t, ontMetrics.DownBps, coreMetrics.DownBps, "core1 should aggregate ont1 traffic")
}

// TestGenerateFlows_MultipleONTs tests aggregation with multiple leaf devices
func TestGenerateFlows_MultipleONTs(t *testing.T) {
	// Arrange: 2 ONTs → 1 OLT → Core
	devices := []models.Device{
		{
			ID:          "core1",
			Type:        models.DeviceTypeCoreRouter,
			Status:      "UP",
			Provisioned: true,
		},
		{
			ID:          "olt1",
			Type:        models.DeviceTypeOLT,
			Status:      "UP",
			Provisioned: true,
		},
		{
			ID:          "ont1",
			Type:        models.DeviceTypeBusinessONT,
			Status:      "UP",
			Provisioned: true,
			TariffID:    sql.NullInt64{Int64: 1, Valid: true},
		},
		{
			ID:          "ont2",
			Type:        models.DeviceTypeBusinessONT,
			Status:      "UP",
			Provisioned: true,
			TariffID:    sql.NullInt64{Int64: 1, Valid: true},
		},
	}

	links := []models.Link{
		{ID: "link1", AInterfaceID: "ont1-eth0", BInterfaceID: "olt1-eth0", Status: "UP"},
		{ID: "link2", AInterfaceID: "ont2-eth0", BInterfaceID: "olt1-eth1", Status: "UP"},
		{ID: "link3", AInterfaceID: "olt1-eth2", BInterfaceID: "core1-eth0", Status: "UP"},
	}

	tariffs := []models.Tariff{
		{ID: 1, MaxUpMbps: 100.0, MaxDownMbps: 500.0},
	}

	cache := buildTestCacheWithTariffs(devices, links, tariffs)
	adj := buildTestAdjacency(cache, links)

	// Act
	result := GenerateFlows(cache, adj, 1, 42)

	// Assert
	assert.Equal(t, 2, result.LeavesCount, "should process 2 leaf devices")
	assert.Len(t, result.DeviceMetrics, 4, "should have metrics for 4 devices (ont1, ont2, olt1, core1)")
	assert.Len(t, result.LinkMetrics, 3, "should have metrics for 3 links")

	// OLT and Core should aggregate traffic from both ONTs
	oltMetrics := result.DeviceMetrics["olt1"]
	coreMetrics := result.DeviceMetrics["core1"]
	ont1Metrics := result.DeviceMetrics["ont1"]
	ont2Metrics := result.DeviceMetrics["ont2"]

	assert.NotNil(t, oltMetrics, "olt1 should have metrics")
	assert.NotNil(t, coreMetrics, "core1 should have metrics")
	assert.NotNil(t, ont1Metrics, "ont1 should have metrics")
	assert.NotNil(t, ont2Metrics, "ont2 should have metrics")

	// OLT and Core traffic should be sum of ONT traffics
	expectedUpBps := ont1Metrics.UpBps + ont2Metrics.UpBps
	expectedDownBps := ont1Metrics.DownBps + ont2Metrics.DownBps

	assert.Equal(t, expectedUpBps, oltMetrics.UpBps, "olt1 should aggregate upstream traffic")
	assert.Equal(t, expectedDownBps, oltMetrics.DownBps, "olt1 should aggregate downstream traffic")
	assert.Equal(t, expectedUpBps, coreMetrics.UpBps, "core1 should aggregate upstream traffic")
	assert.Equal(t, expectedDownBps, coreMetrics.DownBps, "core1 should aggregate downstream traffic")
}

// TestGenerateFlows_SkipUnprovisioned tests that unprovisioned devices are skipped
func TestGenerateFlows_SkipUnprovisioned(t *testing.T) {
	// Arrange: ONT not provisioned
	devices := []models.Device{
		{
			ID:          "olt1",
			Type:        models.DeviceTypeOLT,
			Status:      "UP",
			Provisioned: true,
		},
		{
			ID:          "ont1",
			Type:        models.DeviceTypeBusinessONT,
			Status:      "UP",
			Provisioned: false, // Not provisioned!
			TariffID:    sql.NullInt64{Int64: 1, Valid: true},
		},
	}

	links := []models.Link{
		{ID: "link1", AInterfaceID: "ont1-eth0", BInterfaceID: "olt1-eth0", Status: "UP"},
	}

	tariffs := []models.Tariff{
		{ID: 1, MaxUpMbps: 100.0, MaxDownMbps: 500.0},
	}

	cache := buildTestCacheWithTariffs(devices, links, tariffs)
	adj := buildTestAdjacency(cache, links)

	// Act
	result := GenerateFlows(cache, adj, 1, 42)

	// Assert: No traffic should be generated
	assert.Equal(t, 0, result.LeavesCount, "should not process unprovisioned devices")
	assert.Len(t, result.DeviceMetrics, 0, "should have no device metrics")
	assert.Len(t, result.LinkMetrics, 0, "should have no link metrics")
}

// TestGenerateFlows_SkipDownLeaf tests HGO-007: DOWN provisioned leaves generate no traffic.
func TestGenerateFlows_SkipDownLeaf(t *testing.T) {
	devices := []models.Device{
		{
			ID:          "core1",
			Type:        models.DeviceTypeCoreRouter,
			Status:      "UP",
			Provisioned: true,
		},
		{
			ID:          "olt1",
			Type:        models.DeviceTypeOLT,
			Status:      "UP",
			Provisioned: true,
		},
		{
			ID:          "ont1",
			Type:        models.DeviceTypeBusinessONT,
			Status:      "DOWN",
			Provisioned: true,
			TariffID:    sql.NullInt64{Int64: 1, Valid: true},
		},
	}

	links := []models.Link{
		{ID: "link1", AInterfaceID: "ont1-eth0", BInterfaceID: "olt1-eth0", Status: "UP"},
		{ID: "link2", AInterfaceID: "olt1-eth1", BInterfaceID: "core1-eth0", Status: "UP"},
	}
	tariffs := []models.Tariff{
		{ID: 1, MaxUpMbps: 100.0, MaxDownMbps: 500.0},
	}

	cache := buildTestCacheWithTariffs(devices, links, tariffs)
	adj := buildTestAdjacency(cache, links)

	result := GenerateFlows(cache, adj, 1, 42)

	assert.Equal(t, 0, result.LeavesCount, "DOWN leaf should not be processed")
	assert.Len(t, result.DeviceMetrics, 0, "DOWN leaf should emit no device metrics")
	assert.Len(t, result.LinkMetrics, 0, "DOWN leaf should emit no link metrics")
}

// TestGenerateFlows_SkipNoTariff tests that devices without tariff are skipped
func TestGenerateFlows_SkipNoTariff(t *testing.T) {
	// Arrange: ONT without tariff
	devices := []models.Device{
		{
			ID:          "olt1",
			Type:        models.DeviceTypeOLT,
			Status:      "UP",
			Provisioned: true,
		},
		{
			ID:          "ont1",
			Type:        models.DeviceTypeBusinessONT,
			Status:      "UP",
			Provisioned: true,
			TariffID:    sql.NullInt64{Valid: false}, // No tariff!
		},
	}

	links := []models.Link{
		{ID: "link1", AInterfaceID: "ont1-eth0", BInterfaceID: "olt1-eth0", Status: "UP"},
	}

	cache := buildTestCacheWithTariffs(devices, links, []models.Tariff{})
	adj := buildTestAdjacency(cache, links)

	// Act
	result := GenerateFlows(cache, adj, 1, 42)

	// Assert: No traffic should be generated
	assert.Equal(t, 0, result.LeavesCount, "should not process devices without tariff")
	assert.Len(t, result.DeviceMetrics, 0, "should have no device metrics")
	assert.Len(t, result.LinkMetrics, 0, "should have no link metrics")
}

// TestGenerateFlows_DeterministicOutput tests that same seed → same output
func TestGenerateFlows_DeterministicOutput(t *testing.T) {
	// Arrange: Simple topology with Core
	devices := []models.Device{
		{
			ID:          "core1",
			Type:        models.DeviceTypeCoreRouter,
			Status:      "UP",
			Provisioned: true,
		},
		{
			ID:          "olt1",
			Type:        models.DeviceTypeOLT,
			Status:      "UP",
			Provisioned: true,
		},
		{
			ID:          "ont1",
			Type:        models.DeviceTypeBusinessONT,
			Status:      "UP",
			Provisioned: true,
			TariffID:    sql.NullInt64{Int64: 1, Valid: true},
		},
	}

	links := []models.Link{
		{ID: "link1", AInterfaceID: "ont1-eth0", BInterfaceID: "olt1-eth0", Status: "UP"},
		{ID: "link2", AInterfaceID: "olt1-eth1", BInterfaceID: "core1-eth0", Status: "UP"},
	}

	tariffs := []models.Tariff{
		{ID: 1, MaxUpMbps: 100.0, MaxDownMbps: 500.0},
	}

	cache := buildTestCacheWithTariffs(devices, links, tariffs)
	adj := buildTestAdjacency(cache, links)

	// Act: Generate flows 3 times with same seed
	seed := 42
	tick := 10
	result1 := GenerateFlows(cache, adj, tick, seed)
	result2 := GenerateFlows(cache, adj, tick, seed)
	result3 := GenerateFlows(cache, adj, tick, seed)

	// Assert: All results should be identical
	assert.Equal(t, result1.LeavesCount, result2.LeavesCount, "leaves count should be deterministic")
	assert.Equal(t, result1.LeavesCount, result3.LeavesCount, "leaves count should be deterministic")

	assert.Equal(t, result1.DeviceMetrics["ont1"].UpBps, result2.DeviceMetrics["ont1"].UpBps, "ont1 up traffic should be deterministic")
	assert.Equal(t, result1.DeviceMetrics["ont1"].UpBps, result3.DeviceMetrics["ont1"].UpBps, "ont1 up traffic should be deterministic")
	assert.Equal(t, result1.DeviceMetrics["ont1"].DownBps, result2.DeviceMetrics["ont1"].DownBps, "ont1 down traffic should be deterministic")
	assert.Equal(t, result1.DeviceMetrics["ont1"].DownBps, result3.DeviceMetrics["ont1"].DownBps, "ont1 down traffic should be deterministic")
}

// Helper: buildTestCache creates a minimal topology cache for testing
func buildTestCache(devices []models.Device, links []models.Link) *models.TopologyCache {
	cache := &models.TopologyCache{
		DeviceByID:       make(map[string]*models.Device),
		InterfaceByID:    make(map[string]*models.Interface),
		LinksByInterface: make(map[string][]models.Link),
		LinkByID:         make(map[string]*models.Link),
		TariffByID:       make(map[int64]*models.Tariff),
	}

	// Add devices
	for i := range devices {
		cache.DeviceByID[devices[i].ID] = &devices[i]
	}

	// Add interfaces (auto-generate from links)
	for _, link := range links {
		if cache.InterfaceByID[link.AInterfaceID] == nil {
			cache.InterfaceByID[link.AInterfaceID] = &models.Interface{
				ID:          link.AInterfaceID,
				DeviceID:    extractDeviceIDFromInterface(link.AInterfaceID),
				AdminStatus: models.AdminStatusUP,
			}
		}
		if cache.InterfaceByID[link.BInterfaceID] == nil {
			cache.InterfaceByID[link.BInterfaceID] = &models.Interface{
				ID:          link.BInterfaceID,
				DeviceID:    extractDeviceIDFromInterface(link.BInterfaceID),
				AdminStatus: models.AdminStatusUP,
			}
		}
	}

	// Add links
	for i := range links {
		cache.LinksByInterface[links[i].AInterfaceID] = append(cache.LinksByInterface[links[i].AInterfaceID], links[i])
		cache.LinksByInterface[links[i].BInterfaceID] = append(cache.LinksByInterface[links[i].BInterfaceID], links[i])
		cache.LinkByID[links[i].ID] = &links[i]
	}

	return cache
}

// Helper: buildTestCacheWithTariffs creates cache with tariff data
func buildTestCacheWithTariffs(devices []models.Device, links []models.Link, tariffs []models.Tariff) *models.TopologyCache {
	cache := buildTestCache(devices, links)

	for i := range tariffs {
		cache.TariffByID[tariffs[i].ID] = &tariffs[i]
	}

	return cache
}

// Helper: buildTestAdjacency creates an adjacency graph from cache + links
func buildTestAdjacency(cache *models.TopologyCache, links []models.Link) *graph.AdjacencyGraph {
	return graph.BuildAdjacency(cache)
}

// Helper: extractDeviceIDFromInterface extracts device ID from interface ID
// Example: "ont1-eth0" → "ont1"
func extractDeviceIDFromInterface(interfaceID string) string {
	for i, c := range interfaceID {
		if c == '-' {
			return interfaceID[:i]
		}
	}
	return interfaceID
}
