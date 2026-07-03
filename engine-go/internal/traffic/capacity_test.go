package traffic

import (
	"database/sql"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/unoc/engine-go/internal/models"
)

func TestDefaultDeviceCapacityMbpsMatchesPythonCatalogEffective(t *testing.T) {
	expected := map[models.DeviceType]float64{
		models.DeviceTypeBackboneGateway: 100_000,
		models.DeviceTypePOP:             10_000,
		models.DeviceTypeCoreRouter:      40_000,
		models.DeviceTypeEdgeRouter:      10_000,
		models.DeviceTypeAONSwitch:       10_000,
		models.DeviceTypeOLT:             10_000,
		models.DeviceTypeONT:             1_000,
		models.DeviceTypeBusinessONT:     1_000,
		models.DeviceTypeAONCPE:          1_000,
		models.DeviceTypeSplitter:        1_000_000,
		models.DeviceTypeHop:             1_000_000,
		models.DeviceTypeNVT:             1_000_000,
		models.DeviceTypeODF:             1_000_000,
	}

	assert.Equal(t, expected, DefaultDeviceCapacityMbps)
}

func TestEffectiveDeviceCapacityPrecedence(t *testing.T) {
	cache := models.BuildTopologyCacheWithCatalog(
		[]models.Device{},
		nil,
		nil,
		nil,
		[]models.HardwareModel{
			{ID: 7, DeviceType: models.DeviceTypeEdgeRouter, CapacityGbps: sql.NullFloat64{Float64: 200, Valid: true}},
		},
		nil,
	)

	withOverride := &models.Device{
		ID:              "edge-override",
		Type:            models.DeviceTypeEdgeRouter,
		Capacity:        sql.NullInt64{Int64: 50_000, Valid: true},
		HardwareModelID: sql.NullInt64{Int64: 7, Valid: true},
	}
	withModel := &models.Device{
		ID:              "edge-model",
		Type:            models.DeviceTypeEdgeRouter,
		HardwareModelID: sql.NullInt64{Int64: 7, Valid: true},
	}
	withDefault := &models.Device{ID: "edge-default", Type: models.DeviceTypeEdgeRouter}

	assert.Equal(t, float64(50_000), EffectiveDeviceCapacityMbps(withOverride, cache))
	assert.Equal(t, float64(200_000), EffectiveDeviceCapacityMbps(withModel, cache))
	assert.Equal(t, float64(10_000), EffectiveDeviceCapacityMbps(withDefault, cache))
}

func TestEffectiveInterfaceCapacityPrecedenceAndProfileBaseMatch(t *testing.T) {
	device := models.Device{
		ID:              "edge1",
		Type:            models.DeviceTypeEdgeRouter,
		HardwareModelID: sql.NullInt64{Int64: 7, Valid: true},
	}
	cache := models.BuildTopologyCacheWithCatalog(
		[]models.Device{device},
		nil,
		nil,
		nil,
		nil,
		[]models.PortProfile{
			{ID: 1, HardwareModelID: 7, Name: "uplink", SpeedGbps: sql.NullFloat64{Float64: 10, Valid: true}},
			{ID: 2, HardwareModelID: 7, Name: "access", SpeedGbps: sql.NullFloat64{Float64: 1, Valid: true}},
		},
	)

	overrideIface := &models.Interface{
		ID:       "edge1-access0",
		DeviceID: "edge1",
		Name:     "access0",
		Capacity: sql.NullInt64{Int64: 2500, Valid: true},
	}
	profileNameIface := &models.Interface{
		ID:          "edge1-any0",
		DeviceID:    "edge1",
		Name:        "any0",
		ProfileName: sql.NullString{String: "uplink", Valid: true},
	}
	baseNameIface := &models.Interface{
		ID:       "edge1-access24",
		DeviceID: "edge1",
		Name:     "access24",
	}
	roleIface := &models.Interface{
		ID:       "edge1-role",
		DeviceID: "edge1",
		Name:     "custom",
		Role:     sql.NullString{String: string(models.InterfaceRoleP2PUplink), Valid: true},
	}

	assert.Equal(t, float64(2500), EffectiveInterfaceCapacityMbps(overrideIface, &device, cache))
	assert.Equal(t, float64(10_000), EffectiveInterfaceCapacityMbps(profileNameIface, &device, cache))
	assert.Equal(t, float64(1_000), EffectiveInterfaceCapacityMbps(baseNameIface, &device, cache))
	assert.Equal(t, float64(10_000), EffectiveInterfaceCapacityMbps(roleIface, &device, cache))
}

func TestEffectiveLinkCapacityPrecedence(t *testing.T) {
	devices := []models.Device{
		{ID: "a", Type: models.DeviceTypeEdgeRouter},
		{ID: "b", Type: models.DeviceTypeOLT},
		{ID: "c", Type: models.DeviceTypeAONSwitch},
	}
	interfaces := []models.Interface{
		{ID: "a-if0", DeviceID: "a", Name: "if0", Capacity: sql.NullInt64{Int64: 10_000, Valid: true}},
		{ID: "b-if0", DeviceID: "b", Name: "if0", Capacity: sql.NullInt64{Int64: 1_000, Valid: true}},
		{ID: "c-if0", DeviceID: "c", Name: "if0"},
	}
	links := []models.Link{
		{ID: "both-known", AInterfaceID: "a-if0", BInterfaceID: "b-if0", Kind: models.LinkTypeFiber},
		{ID: "one-known", AInterfaceID: "a-if0", BInterfaceID: "c-if0", Kind: models.LinkTypeFiber},
		{ID: "fiber-fallback", AInterfaceID: "missing-a", BInterfaceID: "missing-b", Kind: models.LinkTypeFiber},
		{ID: "non-fiber-fallback", AInterfaceID: "missing-a", BInterfaceID: "missing-b", Kind: models.LinkTypeP2P},
	}
	cache := models.BuildTopologyCacheWithCatalog(devices, links, interfaces, nil, nil, nil)

	assert.Equal(t, float64(1_000), EffectiveLinkCapacityMbps(cache.LinkByID["both-known"], cache))
	assert.Equal(t, float64(10_000), EffectiveLinkCapacityMbps(cache.LinkByID["one-known"], cache))
	assert.Equal(t, float64(10_000), EffectiveLinkCapacityMbps(cache.LinkByID["fiber-fallback"], cache))
	assert.Equal(t, float64(1_000), EffectiveLinkCapacityMbps(cache.LinkByID["non-fiber-fallback"], cache))
}

func TestFullDuplexUtilizationUsesMaxDirection(t *testing.T) {
	assert.InDelta(t, 0.60, FullDuplexUtilization(600_000_000, 600_000_000, 1000), 0.0001)
	assert.InDelta(t, 0.95, FullDuplexUtilization(100_000_000, 950_000_000, 1000), 0.0001)
	assert.Equal(t, float64(0), FullDuplexUtilization(1_000_000, 1_000_000, 0))
}
