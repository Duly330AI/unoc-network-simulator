package traffic

import (
	"math"
	"strings"

	"github.com/unoc/engine-go/internal/models"
)

// DefaultDeviceCapacityMbps mirrors backend/services/catalog_effective.py
// DEFAULT_DEVICE_CAPACITY_MBPS. Keep these values in sync to avoid Go/Python
// capacity contradictions in traffic snapshots.
var DefaultDeviceCapacityMbps = map[models.DeviceType]float64{
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

// EffectiveDeviceCapacityMbps resolves device capacity with the same precedence
// as backend/services/catalog_effective.py:
// device override -> hardware model capacity_gbps -> type fallback.
func EffectiveDeviceCapacityMbps(device *models.Device, cache *models.TopologyCache) float64 {
	if device == nil {
		return 0
	}
	if device.Capacity.Valid {
		return positiveOrZero(float64(device.Capacity.Int64))
	}
	if cache != nil && device.HardwareModelID.Valid {
		model := cache.HardwareModelByID[device.HardwareModelID.Int64]
		if model != nil && model.CapacityGbps.Valid {
			return positiveOrZero(model.CapacityGbps.Float64 * 1000)
		}
	}
	return positiveOrZero(DefaultDeviceCapacityMbps[device.Type])
}

// EffectiveInterfaceCapacityMbps resolves interface capacity with the same
// precedence as backend/services/catalog_effective.py:
// interface override -> port profile speed_gbps -> role fallback.
func EffectiveInterfaceCapacityMbps(iface *models.Interface, device *models.Device, cache *models.TopologyCache) float64 {
	if iface == nil {
		return 0
	}
	if iface.Capacity.Valid {
		return positiveOrZero(float64(iface.Capacity.Int64))
	}
	profile := matchingPortProfile(iface, device, cache)
	if profile != nil && profile.SpeedGbps.Valid {
		return positiveOrZero(profile.SpeedGbps.Float64 * 1000)
	}
	return roleDefaultCapacityMbps(iface)
}

// EffectiveLinkCapacityMbps resolves link capacity from endpoint interfaces.
// PhysicalMedium has no capacity/speed field in B1, so link fallback remains
// the prior kind constants only when both endpoint capacities are unknown.
func EffectiveLinkCapacityMbps(link *models.Link, cache *models.TopologyCache) float64 {
	if link == nil || cache == nil {
		return 0
	}
	aCap := endpointInterfaceCapacityMbps(link.AInterfaceID, cache)
	bCap := endpointInterfaceCapacityMbps(link.BInterfaceID, cache)
	switch {
	case aCap > 0 && bCap > 0:
		return math.Min(aCap, bCap)
	case aCap > 0:
		return aCap
	case bCap > 0:
		return bCap
	case link.Kind == models.LinkTypeFiber:
		return 10_000
	default:
		return 1_000
	}
}

// FullDuplexUtilization uses max(up, down) against one scalar capacity because
// B1 capacity is modeled as per-direction full-duplex capacity. Summing both
// directions would create false congestion for symmetric traffic. Asymmetric
// media such as GPON still are not modeled per direction in B1.
func FullDuplexUtilization(upBps, downBps, capacityMbps float64) float64 {
	if capacityMbps <= 0 {
		return 0
	}
	return math.Max(upBps, downBps) / (capacityMbps * 1_000_000)
}

func endpointInterfaceCapacityMbps(interfaceID string, cache *models.TopologyCache) float64 {
	iface := cache.InterfaceByID[interfaceID]
	if iface == nil {
		return 0
	}
	device := cache.DeviceByID[iface.DeviceID]
	return EffectiveInterfaceCapacityMbps(iface, device, cache)
}

func matchingPortProfile(iface *models.Interface, device *models.Device, cache *models.TopologyCache) *models.PortProfile {
	if iface == nil || device == nil || cache == nil || !device.HardwareModelID.Valid {
		return nil
	}
	profiles := cache.PortProfilesByHardwareModel[device.HardwareModelID.Int64]
	if len(profiles) == 0 {
		return nil
	}
	if iface.ProfileName.Valid && iface.ProfileName.String != "" {
		if profile := findProfileByName(profiles, iface.ProfileName.String); profile != nil {
			return profile
		}
	}
	return findProfileByName(profiles, baseFromName(iface.Name))
}

func findProfileByName(profiles []*models.PortProfile, name string) *models.PortProfile {
	if name == "" {
		return nil
	}
	for _, profile := range profiles {
		if profile != nil && profile.Name == name {
			return profile
		}
	}
	return nil
}

func baseFromName(name string) string {
	name = strings.TrimSpace(name)
	i := len(name)
	for i > 0 {
		r := name[i-1]
		if r < '0' || r > '9' {
			break
		}
		i--
	}
	if i == 0 {
		return name
	}
	return name[:i]
}

func roleDefaultCapacityMbps(iface *models.Interface) float64 {
	role := ""
	if iface.Role.Valid {
		role = strings.ToLower(strings.TrimSpace(iface.Role.String))
	}
	portRole := ""
	if iface.PortRole.Valid {
		portRole = strings.ToLower(strings.TrimSpace(iface.PortRole.String))
	}

	switch role {
	case "access", "management", "mgmt":
		return 1_000
	case "p2p_uplink", "uplink":
		return 10_000
	}

	switch portRole {
	case "access":
		return 1_000
	case "uplink":
		return 10_000
	}

	return 0
}

func positiveOrZero(value float64) float64 {
	if value > 0 {
		return value
	}
	return 0
}
