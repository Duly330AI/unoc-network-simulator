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

	// DeviceUtilization maps device_id -> current utilization ratio.
	DeviceUtilization map[string]float64

	// DeviceCapacityMbps maps device_id -> resolved effective capacity.
	DeviceCapacityMbps map[string]float64

	// LinkCongested maps link_id -> is_congested
	LinkCongested map[string]bool

	// LinkUtilization maps link_id -> current utilization ratio.
	LinkUtilization map[string]float64

	// LinkCapacityMbps maps link_id -> resolved effective capacity.
	LinkCapacityMbps map[string]float64

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
		DeviceCongested:    make(map[string]bool),
		DeviceUtilization:  make(map[string]float64),
		DeviceCapacityMbps: make(map[string]float64),
		LinkCongested:      make(map[string]bool),
		LinkUtilization:    make(map[string]float64),
		LinkCapacityMbps:   make(map[string]float64),
		CongestionEvents:   make([]CongestionEvent, 0),
	}
}

// DetectCongestion analyzes traffic metrics and updates congestion state with hysteresis
func DetectCongestion(
	result *GenerationResult,
	cache *models.TopologyCache,
	prevState *CongestionState,
) *CongestionState {
	newState := NewCongestionState()

	// Check device congestion
	for devID, metrics := range result.DeviceMetrics {
		device := cache.DeviceByID[devID]
		if device == nil {
			continue
		}

		capacityMbps := EffectiveDeviceCapacityMbps(device, cache)
		utilization := FullDuplexUtilization(metrics.UpBps, metrics.DownBps, capacityMbps)
		newState.DeviceCapacityMbps[devID] = capacityMbps
		newState.DeviceUtilization[devID] = utilization

		// Apply hysteresis
		wasCongested := false
		if prevState != nil {
			wasCongested = prevState.DeviceCongested[devID]
		}
		isCongested := wasCongested // default: keep previous state

		if device.IsLeaf() || capacityMbps <= 0 {
			// B1 reports leaf utilization but does not mark ONT/BUSINESS_ONT/AON_CPE
			// congestion until B2 shaping can distinguish requested from delivered traffic.
			isCongested = false
		} else {
			if wasCongested {
				// Currently congested: clear only when utilization drops below LOW threshold.
				if utilization < CongestionThresholdLow {
					isCongested = false
					log.Info().
						Str("device_id", devID).
						Float64("utilization", utilization).
						Float64("capacity_mbps", capacityMbps).
						Msg("Device congestion cleared (hysteresis)")
				}
			} else {
				// Currently normal: enter congestion at the HIGH threshold.
				if utilization >= CongestionThresholdHigh {
					isCongested = true
					log.Warn().
						Str("device_id", devID).
						Float64("utilization", utilization).
						Float64("capacity_mbps", capacityMbps).
						Msg("Device congestion detected")
				}
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

		capacityMbps := EffectiveLinkCapacityMbps(link, cache)
		utilization := FullDuplexUtilization(metrics.UpBps, metrics.DownBps, capacityMbps)
		newState.LinkCapacityMbps[linkID] = capacityMbps
		newState.LinkUtilization[linkID] = utilization

		// Apply hysteresis
		wasCongested := false
		if prevState != nil {
			wasCongested = prevState.LinkCongested[linkID]
		}
		isCongested := wasCongested // default: keep previous state

		if capacityMbps <= 0 {
			isCongested = false
		} else {
			if wasCongested {
				// Currently congested: clear only when utilization drops below LOW threshold.
				if utilization < CongestionThresholdLow {
					isCongested = false
					log.Info().
						Str("link_id", linkID).
						Float64("utilization", utilization).
						Float64("capacity_mbps", capacityMbps).
						Msg("Link congestion cleared (hysteresis)")
				}
			} else {
				// Currently normal: enter congestion at the HIGH threshold.
				if utilization >= CongestionThresholdHigh {
					isCongested = true
					log.Warn().
						Str("link_id", linkID).
						Float64("utilization", utilization).
						Float64("capacity_mbps", capacityMbps).
						Msg("Link congestion detected")
				}
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
