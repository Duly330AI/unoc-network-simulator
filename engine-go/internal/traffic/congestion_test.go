package traffic

import (
	"database/sql"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/unoc/engine-go/internal/models"
)

func TestDetectCongestionFullDuplexUtilizationDoesNotSumDirections(t *testing.T) {
	cache := newCongestionTestCache(
		[]models.Device{
			{ID: "edge1", Type: models.DeviceTypeEdgeRouter, Status: models.StatusUP, Capacity: sql.NullInt64{Int64: 1000, Valid: true}},
		},
		nil,
		nil,
	)
	result := &GenerationResult{
		DeviceMetrics: map[string]*FlowMetrics{
			"edge1": {UpBps: 600_000_000, DownBps: 600_000_000},
		},
		LinkMetrics: map[string]*FlowMetrics{},
	}

	state := DetectCongestion(result, cache, NewCongestionState())

	assert.InDelta(t, 0.60, state.DeviceUtilization["edge1"], 0.0001)
	assert.Equal(t, float64(1000), state.DeviceCapacityMbps["edge1"])
	assert.False(t, state.DeviceCongested["edge1"])
	assert.Empty(t, state.CongestionEvents)
}

func TestDetectCongestionDeviceHysteresisBoundaries(t *testing.T) {
	cache := newCongestionTestCache(
		[]models.Device{
			{ID: "edge1", Type: models.DeviceTypeEdgeRouter, Status: models.StatusUP, Capacity: sql.NullInt64{Int64: 1000, Valid: true}},
		},
		nil,
		nil,
	)

	state := DetectCongestion(&GenerationResult{
		DeviceMetrics: map[string]*FlowMetrics{"edge1": {DownBps: 900_000_000}},
		LinkMetrics:   map[string]*FlowMetrics{},
	}, cache, NewCongestionState())
	assert.True(t, state.DeviceCongested["edge1"], "enters congestion at 90%")

	state = DetectCongestion(&GenerationResult{
		DeviceMetrics: map[string]*FlowMetrics{"edge1": {DownBps: 850_000_000}},
		LinkMetrics:   map[string]*FlowMetrics{},
	}, cache, state)
	assert.True(t, state.DeviceCongested["edge1"], "clears only below 85%, not at 85%")

	state = DetectCongestion(&GenerationResult{
		DeviceMetrics: map[string]*FlowMetrics{"edge1": {DownBps: 849_000_000}},
		LinkMetrics:   map[string]*FlowMetrics{},
	}, cache, state)
	assert.False(t, state.DeviceCongested["edge1"], "clears below 85%")
}

func TestDetectCongestionLeavesReportUtilizationButNeverCongestInB1(t *testing.T) {
	cache := newCongestionTestCache(
		[]models.Device{
			{ID: "ont1", Type: models.DeviceTypeBusinessONT, Status: models.StatusUP, Capacity: sql.NullInt64{Int64: 100, Valid: true}},
			{ID: "cpe1", Type: models.DeviceTypeAONCPE, Status: models.StatusUP, Capacity: sql.NullInt64{Int64: 100, Valid: true}},
		},
		nil,
		nil,
	)
	result := &GenerationResult{
		DeviceMetrics: map[string]*FlowMetrics{
			"ont1": {DownBps: 500_000_000},
			"cpe1": {UpBps: 500_000_000},
		},
		LinkMetrics: map[string]*FlowMetrics{},
	}

	state := DetectCongestion(result, cache, NewCongestionState())

	assert.InDelta(t, 5.0, state.DeviceUtilization["ont1"], 0.0001)
	assert.InDelta(t, 5.0, state.DeviceUtilization["cpe1"], 0.0001)
	assert.False(t, state.DeviceCongested["ont1"])
	assert.False(t, state.DeviceCongested["cpe1"])
	assert.Empty(t, state.CongestionEvents)
}

func TestDetectCongestionUnknownDeviceCapacityIsNotCongested(t *testing.T) {
	cache := newCongestionTestCache(
		[]models.Device{
			{ID: "site1", Type: models.DeviceTypeCoreSite, Status: models.StatusUP},
		},
		nil,
		nil,
	)
	result := &GenerationResult{
		DeviceMetrics: map[string]*FlowMetrics{"site1": {DownBps: 10_000_000_000}},
		LinkMetrics:   map[string]*FlowMetrics{},
	}

	state := DetectCongestion(result, cache, NewCongestionState())

	assert.Equal(t, float64(0), state.DeviceCapacityMbps["site1"])
	assert.Equal(t, float64(0), state.DeviceUtilization["site1"])
	assert.False(t, state.DeviceCongested["site1"])
}

func TestDetectCongestionLinkUsesEffectiveInterfaceCapacity(t *testing.T) {
	cache := newCongestionTestCache(
		[]models.Device{
			{ID: "edge1", Type: models.DeviceTypeEdgeRouter, Status: models.StatusUP},
			{ID: "olt1", Type: models.DeviceTypeOLT, Status: models.StatusUP},
		},
		[]models.Interface{
			{ID: "edge1-uplink0", DeviceID: "edge1", Name: "uplink0", Capacity: sql.NullInt64{Int64: 10_000, Valid: true}},
			{ID: "olt1-uplink0", DeviceID: "olt1", Name: "uplink0", Capacity: sql.NullInt64{Int64: 1_000, Valid: true}},
		},
		[]models.Link{
			{ID: "l1", AInterfaceID: "edge1-uplink0", BInterfaceID: "olt1-uplink0", Status: models.StatusUP, Kind: models.LinkTypeFiber},
		},
	)
	result := &GenerationResult{
		DeviceMetrics: map[string]*FlowMetrics{},
		LinkMetrics:   map[string]*FlowMetrics{"l1": {DownBps: 950_000_000}},
	}

	state := DetectCongestion(result, cache, NewCongestionState())

	assert.Equal(t, float64(1000), state.LinkCapacityMbps["l1"])
	assert.InDelta(t, 0.95, state.LinkUtilization["l1"], 0.0001)
	assert.True(t, state.LinkCongested["l1"])
}

func newCongestionTestCache(
	devices []models.Device,
	interfaces []models.Interface,
	links []models.Link,
) *models.TopologyCache {
	return models.BuildTopologyCacheWithCatalog(devices, links, interfaces, nil, nil, nil)
}
