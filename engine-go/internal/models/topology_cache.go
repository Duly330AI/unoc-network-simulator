package models

import "github.com/rs/zerolog/log"

// TopologyCache provides O(1) lookup maps for topology data
type TopologyCache struct {
	DeviceByID                  map[string]*Device
	LinkByID                    map[string]*Link  // link_id -> link (NEW for HGO-006)
	LinksByInterface            map[string][]Link // interface_id -> links connected to it
	InterfaceByID               map[string]*Interface
	TariffByID                  map[int64]*Tariff
	HardwareModelByID           map[int64]*HardwareModel
	PortProfilesByHardwareModel map[int64][]*PortProfile
}

// BuildTopologyCache creates index maps from raw data for fast lookups
func BuildTopologyCache(devices []Device, links []Link, interfaces []Interface, tariffs []Tariff) *TopologyCache {
	return BuildTopologyCacheWithCatalog(devices, links, interfaces, tariffs, nil, nil)
}

// BuildTopologyCacheWithCatalog creates index maps including catalog rows used by capacity logic.
func BuildTopologyCacheWithCatalog(
	devices []Device,
	links []Link,
	interfaces []Interface,
	tariffs []Tariff,
	hardwareModels []HardwareModel,
	portProfiles []PortProfile,
) *TopologyCache {
	cache := &TopologyCache{
		DeviceByID:                  make(map[string]*Device, len(devices)),
		LinkByID:                    make(map[string]*Link, len(links)),
		LinksByInterface:            make(map[string][]Link, len(interfaces)),
		InterfaceByID:               make(map[string]*Interface, len(interfaces)),
		TariffByID:                  make(map[int64]*Tariff, len(tariffs)),
		HardwareModelByID:           make(map[int64]*HardwareModel, len(hardwareModels)),
		PortProfilesByHardwareModel: make(map[int64][]*PortProfile, len(portProfiles)),
	}

	// Index devices
	for i := range devices {
		cache.DeviceByID[devices[i].ID] = &devices[i]
	}

	// Index interfaces
	for i := range interfaces {
		cache.InterfaceByID[interfaces[i].ID] = &interfaces[i]
	}

	// Index tariffs
	for i := range tariffs {
		cache.TariffByID[tariffs[i].ID] = &tariffs[i]
	}

	// Index hardware models and port profiles
	for i := range hardwareModels {
		cache.HardwareModelByID[hardwareModels[i].ID] = &hardwareModels[i]
	}

	for i := range portProfiles {
		profile := &portProfiles[i]
		cache.PortProfilesByHardwareModel[profile.HardwareModelID] = append(cache.PortProfilesByHardwareModel[profile.HardwareModelID], profile)
	}

	// Index links by ID and by connected interfaces
	for i := range links {
		cache.LinkByID[links[i].ID] = &links[i]
		cache.LinksByInterface[links[i].AInterfaceID] = append(cache.LinksByInterface[links[i].AInterfaceID], links[i])
		cache.LinksByInterface[links[i].BInterfaceID] = append(cache.LinksByInterface[links[i].BInterfaceID], links[i])
	}

	log.Info().
		Int("devices", len(cache.DeviceByID)).
		Int("interfaces", len(cache.InterfaceByID)).
		Int("links", len(links)).
		Int("tariffs", len(cache.TariffByID)).
		Int("hardware_models", len(cache.HardwareModelByID)).
		Int("port_profiles", len(portProfiles)).
		Msg("Built topology cache")

	return cache
}
