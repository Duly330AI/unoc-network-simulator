package traffic

import (
	"github.com/rs/zerolog/log"
	"github.com/unoc/engine-go/internal/models"
)

const (
	// CongestionThresholdHigh: Utilization threshold to trigger congestion (90%)
	CongestionThresholdHigh = 0.90

	// CongestionThresholdLow: Utilization threshold to clear congestion (85% - hysteresis)
	CongestionThresholdLow = 0.85
)

// CongestionState tracks congestion status for devices and links
type CongestionState struct {
	// DeviceCongested maps device_id -> is_congested
	DeviceCongested map[string]bool

	// LinkCongested maps link_id -> is_congested
	LinkCongested map[string]bool

	// CongestionEvents tracks transitions for this tick (for event emission)
	CongestionEvents []CongestionEvent
}

// CongestionEvent represents a congestion state change
type CongestionEvent struct {
	EntityType  string  // "device" or "link"
	EntityID    string  // device_id or link_id
	OldState    bool    // previous congestion state
	NewState    bool    // new congestion state
	Utilization float64 // current utilization (0.0-1.0)
}

// NewCongestionState creates a new congestion state tracker
func NewCongestionState() *CongestionState {
	return &CongestionState{
		DeviceCongested:  make(map[string]bool),
		LinkCongested:    make(map[string]bool),
		CongestionEvents: make([]CongestionEvent, 0),
	}
}

// DetectCongestion analyzes traffic metrics and updates congestion state with hysteresis
func DetectCongestion(
	result *GenerationResult,
	cache *models.TopologyCache,
	prevState *CongestionState,
) *CongestionState {
	newState := NewCongestionState()

	// Copy previous state for hysteresis
	for devID, wasCongested := range prevState.DeviceCongested {
		newState.DeviceCongested[devID] = wasCongested
	}
	for linkID, wasCongested := range prevState.LinkCongested {
		newState.LinkCongested[linkID] = wasCongested
	}

	// Check device congestion
	for devID, metrics := range result.DeviceMetrics {
		device := cache.DeviceByID[devID]
		if device == nil {
			continue
		}

		// Compute utilization (traffic / capacity)
		// For devices, capacity is typically sum of interface capacities or tariff max
		var utilization float64
		if device.Type == models.DeviceTypeONT || device.Type == models.DeviceTypeBusinessONT {
			// For ONTs, use tariff capacity
			if device.TariffID.Valid {
				tariff := cache.TariffByID[device.TariffID.Int64]
				if tariff != nil {
					capacityBps := (tariff.MaxDownMbps + tariff.MaxUpMbps) * 1_000_000
					trafficBps := metrics.DownBps + metrics.UpBps
					if capacityBps > 0 {
						utilization = trafficBps / capacityBps
					}
				}
			}
		} else {
			// For other devices, use sum of interface capacities (if available)
			// For now, skip non-leaf devices (TODO: aggregate interface capacity)
			continue
		}

		// Apply hysteresis
		wasCongested := newState.DeviceCongested[devID]
		isCongested := wasCongested // default: keep previous state

		// NOTE: Debug level on purpose. ONT self-utilization is demand/tariff and
		// oscillates 0.8-1.0 with the random factor, so these transitions ping-pong
		// every few ticks and flooded the log at Warn. Proper device capacity
		// semantics are Batch B scope; link congestion below stays at Warn.
		if wasCongested {
			// Currently congested: only clear if utilization drops below LOW threshold
			if utilization < CongestionThresholdLow {
				isCongested = false
				log.Debug().
					Str("device_id", devID).
					Float64("utilization", utilization).
					Msg("Device congestion cleared (hysteresis)")
			}
		} else {
			// Currently normal: only trigger if utilization exceeds HIGH threshold
			if utilization >= CongestionThresholdHigh {
				isCongested = true
				log.Debug().
					Str("device_id", devID).
					Float64("utilization", utilization).
					Msg("Device congestion detected")
			}
		}

		// Update state and emit event if changed
		newState.DeviceCongested[devID] = isCongested
		if isCongested != wasCongested {
			newState.CongestionEvents = append(newState.CongestionEvents, CongestionEvent{
				EntityType:  "device",
				EntityID:    devID,
				OldState:    wasCongested,
				NewState:    isCongested,
				Utilization: utilization,
			})
		}
	}

	// Check link congestion
	for linkID, metrics := range result.LinkMetrics {
		link := cache.LinkByID[linkID]
		if link == nil {
			continue
		}

		// Get link capacity from PhysicalMedium (if available)
		// For now, use fixed capacity (TODO: fetch from Link model or PhysicalMedium)
		var capacityMbps float64
		// Typical link capacities:
		// - Fiber: 10G (10000 Mbps)
		// - PON: 2.5G (2500 Mbps)
		// - Ethernet: 1G (1000 Mbps)
		if link.Kind == models.LinkTypeFiber {
			capacityMbps = 10000.0 // 10G default
		} else {
			capacityMbps = 1000.0 // 1G default
		}

		capacityBps := capacityMbps * 1_000_000
		trafficBps := metrics.DownBps + metrics.UpBps
		utilization := trafficBps / capacityBps

		// Apply hysteresis
		wasCongested := newState.LinkCongested[linkID]
		isCongested := wasCongested // default: keep previous state

		if wasCongested {
			// Currently congested: only clear if utilization drops below LOW threshold
			if utilization < CongestionThresholdLow {
				isCongested = false
				log.Info().
					Str("link_id", linkID).
					Float64("utilization", utilization).
					Msg("Link congestion cleared (hysteresis)")
			}
		} else {
			// Currently normal: only trigger if utilization exceeds HIGH threshold
			if utilization >= CongestionThresholdHigh {
				isCongested = true
				log.Warn().
					Str("link_id", linkID).
					Float64("utilization", utilization).
					Msg("Link congestion detected")
			}
		}

		// Update state and emit event if changed
		newState.LinkCongested[linkID] = isCongested
		if isCongested != wasCongested {
			newState.CongestionEvents = append(newState.CongestionEvents, CongestionEvent{
				EntityType:  "link",
				EntityID:    linkID,
				OldState:    wasCongested,
				NewState:    isCongested,
				Utilization: utilization,
			})
		}
	}

	// Log summary
	congestedDevices := 0
	congestedLinks := 0
	for _, isCongested := range newState.DeviceCongested {
		if isCongested {
			congestedDevices++
		}
	}
	for _, isCongested := range newState.LinkCongested {
		if isCongested {
			congestedLinks++
		}
	}

	// State CHANGES are logged above (Warn/Info); the steady-state summary would
	// otherwise fire every tick for as long as anything stays congested.
	if len(newState.CongestionEvents) > 0 {
		log.Info().
			Int("congested_devices", congestedDevices).
			Int("congested_links", congestedLinks).
			Int("state_changes", len(newState.CongestionEvents)).
			Msg("Congestion detection completed")
	}

	return newState
}

// GetCongestedEntities returns lists of currently congested device/link IDs
func (cs *CongestionState) GetCongestedEntities() ([]string, []string) {
	congestedDevices := make([]string, 0)
	congestedLinks := make([]string, 0)

	for devID, isCongested := range cs.DeviceCongested {
		if isCongested {
			congestedDevices = append(congestedDevices, devID)
		}
	}

	for linkID, isCongested := range cs.LinkCongested {
		if isCongested {
			congestedLinks = append(congestedLinks, linkID)
		}
	}

	return congestedDevices, congestedLinks
}
