package api

import (
	"context"
	"net/http"
	"sync"
	"sync/atomic"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/rs/zerolog/log"
	"github.com/unoc/engine-go/internal/db"
	"github.com/unoc/engine-go/internal/graph"
	"github.com/unoc/engine-go/internal/models"
	"github.com/unoc/engine-go/internal/traffic"
)

// Global state (in-memory cache of latest metrics)
var (
	latestSnapshot  *SnapshotResponse
	tickCounter     int64                    // HGO-008 Phase 5: Changed to int64 for atomic ops
	congestionState *traffic.CongestionState // HGO-006: Persistent congestion state
	congestionMutex sync.RWMutex             // HGO-008 Phase 5: Protect congestionState
	snapshotMutex   sync.RWMutex             // HGO-008 Phase 5: Protect latestSnapshot
)

// init initializes global state
func init() {
	congestionState = traffic.NewCongestionState()
}

// TickRequest represents the request body for POST /api/v1/tick
type TickRequest struct {
	Tick       int `json:"tick,omitempty"`        // Optional tick number from Python
	RandomSeed int `json:"random_seed,omitempty"` // Optional random seed
}

// TickResponse represents the response for POST /api/v1/tick
type TickResponse struct {
	Success            bool    `json:"success"`
	Tick               int     `json:"tick"`
	Timestamp          string  `json:"timestamp"` // ISO8601 timestamp
	LeavesCount        int     `json:"leaves_count"`
	DevicesWithTraffic int     `json:"devices_with_traffic"`
	LinksWithTraffic   int     `json:"links_with_traffic"`
	CongestedDevices   int     `json:"congested_devices"` // HGO-006
	CongestedLinks     int     `json:"congested_links"`   // HGO-006
	DurationMs         float64 `json:"duration_ms"`
	Message            string  `json:"message,omitempty"`
}

// SnapshotResponse represents the response for GET /api/v1/snapshot
type SnapshotResponse struct {
	Tick          int                       `json:"tick"`
	Timestamp     string                    `json:"timestamp"`
	DeviceMetrics map[string]*DeviceMetrics `json:"device_metrics"`
	LinkMetrics   map[string]*LinkMetrics   `json:"link_metrics"`
	LeavesCount   int                       `json:"leaves_count"`
}

// DeviceMetrics represents traffic metrics for a device
type DeviceMetrics struct {
	UpBps       float64 `json:"up_bps"`
	DownBps     float64 `json:"down_bps"`
	UpMbps      float64 `json:"up_mbps"`
	DownMbps    float64 `json:"down_mbps"`
	Utilization float64 `json:"utilization"`
	Congested   bool    `json:"congested"` // HGO-006: Congestion state
}

// LinkMetrics represents traffic metrics for a link
type LinkMetrics struct {
	UpBps        float64 `json:"up_bps"`
	DownBps      float64 `json:"down_bps"`
	TrafficMbps  float64 `json:"traffic_mbps"`
	CapacityMbps float64 `json:"capacity_mbps"`
	Utilization  float64 `json:"utilization"`
	Congested    bool    `json:"congested"` // HGO-006: Congestion state
}

// tickHandler handles POST /api/v1/tick
// Triggers traffic generation and returns summary
func (s *Server) tickHandler(c *gin.Context) {
	start := time.Now()

	// Parse request body
	var req TickRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		// No body is fine, use defaults
		req.Tick = 0
		req.RandomSeed = 0xAA55AA55
	}

	// Use provided tick or increment counter
	var tick int
	if req.Tick > 0 {
		// Explicit tick provided by client
		tick = req.Tick
		atomic.StoreInt64(&tickCounter, int64(tick)) // HGO-008 Phase 5: Atomic write
	} else {
		// Auto-increment (thread-safe)
		tick = int(atomic.AddInt64(&tickCounter, 1)) // HGO-008 Phase 5: Atomic increment
	}

	randomSeed := req.RandomSeed
	if randomSeed == 0 {
		randomSeed = 0xAA55AA55
	}

	ctx, cancel := context.WithTimeout(c.Request.Context(), 30*time.Second)
	defer cancel()

	// Fetch topology from database
	log.Debug().Int("tick", tick).Msg("Starting traffic tick")

	devices, err := db.FetchAllDevices(ctx)
	if err != nil {
		log.Error().Err(err).Msg("Failed to fetch devices")
		c.JSON(http.StatusInternalServerError, gin.H{
			"success": false,
			"error":   "Failed to fetch devices: " + err.Error(),
		})
		return
	}

	links, err := db.FetchAllLinks(ctx)
	if err != nil {
		log.Error().Err(err).Msg("Failed to fetch links")
		c.JSON(http.StatusInternalServerError, gin.H{
			"success": false,
			"error":   "Failed to fetch links: " + err.Error(),
		})
		return
	}

	interfaces, err := db.FetchAllInterfaces(ctx)
	if err != nil {
		log.Error().Err(err).Msg("Failed to fetch interfaces")
		c.JSON(http.StatusInternalServerError, gin.H{
			"success": false,
			"error":   "Failed to fetch interfaces: " + err.Error(),
		})
		return
	}

	tariffs, err := db.FetchAllTariffs(ctx)
	if err != nil {
		log.Error().Err(err).Msg("Failed to fetch tariffs")
		c.JSON(http.StatusInternalServerError, gin.H{
			"success": false,
			"error":   "Failed to fetch tariffs: " + err.Error(),
		})
		return
	}

	// Build topology cache
	cache := models.BuildTopologyCache(devices, links, interfaces, tariffs)

	// Build adjacency graph
	adjacency := graph.BuildAdjacency(cache)

	// Generate traffic flows
	result := traffic.GenerateFlows(cache, adjacency, tick, randomSeed)

	// HGO-006: Detect congestion with hysteresis (90%/85% thresholds)
	// HGO-008 Phase 5: Protect global state with mutex
	congestionMutex.Lock()
	congestionState = traffic.DetectCongestion(result, cache, congestionState)
	congestionMutex.Unlock()

	// Store snapshot for GET /api/v1/snapshot
	// HGO-008 Phase 5: Build snapshot locally first, then store with lock
	snapshot := &SnapshotResponse{
		Tick:          tick,
		Timestamp:     time.Now().UTC().Format(time.RFC3339),
		DeviceMetrics: make(map[string]*DeviceMetrics),
		LinkMetrics:   make(map[string]*LinkMetrics),
		LeavesCount:   result.LeavesCount,
	}

	// HGO-008 Phase 5: Read congestion state with RLock
	congestionMutex.RLock()
	for devID, metrics := range result.DeviceMetrics {
		isCongested := congestionState.DeviceCongested[devID]

		// Compute utilization for ONTs (tariff-based)
		var utilization float64 = 0.0 // Explicit 0.0 for JSON encoding
		device := cache.DeviceByID[devID]
		if device != nil && (device.Type == models.DeviceTypeONT || device.Type == models.DeviceTypeBusinessONT) {
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
		}

		snapshot.DeviceMetrics[devID] = &DeviceMetrics{
			UpBps:       metrics.UpBps,
			DownBps:     metrics.DownBps,
			UpMbps:      metrics.UpBps / 1_000_000,
			DownMbps:    metrics.DownBps / 1_000_000,
			Utilization: utilization,
			Congested:   isCongested,
		}
	}

	for linkID, metrics := range result.LinkMetrics {
		isCongested := congestionState.LinkCongested[linkID]

		// Compute utilization (traffic / capacity)
		var utilization float64
		var capacityMbps float64
		link := cache.LinkByID[linkID]
		if link != nil {
			if link.Kind == models.LinkTypeFiber {
				capacityMbps = 10000.0 // 10G default
			} else {
				capacityMbps = 1000.0 // 1G default
			}
			capacityBps := capacityMbps * 1_000_000
			trafficBps := metrics.DownBps + metrics.UpBps
			if capacityBps > 0 {
				utilization = trafficBps / capacityBps
			}
		}

		snapshot.LinkMetrics[linkID] = &LinkMetrics{
			UpBps:        metrics.UpBps,
			DownBps:      metrics.DownBps,
			TrafficMbps:  (metrics.UpBps + metrics.DownBps) / 1_000_000,
			CapacityMbps: capacityMbps,
			Utilization:  utilization,
			Congested:    isCongested,
		}
	}
	congestionMutex.RUnlock() // HGO-008 Phase 5: Done reading congestion state

	duration := time.Since(start)

	// HGO-008 Phase 5: Count congested entities with RLock
	congestionMutex.RLock()
	congestedDevices, congestedLinks := congestionState.GetCongestedEntities()
	congestionMutex.RUnlock()

	// HGO-008 Phase 5: Store snapshot with write lock
	snapshotMutex.Lock()
	latestSnapshot = snapshot
	snapshotMutex.Unlock()

	log.Debug().
		Int("tick", tick).
		Int("leaves", result.LeavesCount).
		Int("devices_with_traffic", len(result.DeviceMetrics)).
		Int("links_with_traffic", len(result.LinkMetrics)).
		Int("congested_devices", len(congestedDevices)).
		Int("congested_links", len(congestedLinks)).
		Dur("duration_ms", duration).
		Msg("Traffic tick completed")

	c.JSON(http.StatusOK, TickResponse{
		Success:            true,
		Tick:               tick,
		Timestamp:          time.Now().UTC().Format(time.RFC3339),
		LeavesCount:        result.LeavesCount,
		DevicesWithTraffic: len(result.DeviceMetrics),
		LinksWithTraffic:   len(result.LinkMetrics),
		CongestedDevices:   len(congestedDevices),
		CongestedLinks:     len(congestedLinks),
		DurationMs:         float64(duration.Milliseconds()),
		Message:            "Traffic tick completed successfully",
	})
}

// snapshotHandler handles GET /api/v1/snapshot
// Returns the latest traffic metrics
func (s *Server) snapshotHandler(c *gin.Context) {
	// HGO-008 Phase 5: Protect snapshot read with RLock
	snapshotMutex.RLock()
	snapshot := latestSnapshot
	snapshotMutex.RUnlock()

	if snapshot == nil {
		c.JSON(http.StatusNotFound, gin.H{
			"error":   "No snapshot available",
			"message": "Run POST /api/v1/tick first to generate traffic",
		})
		return
	}

	c.JSON(http.StatusOK, snapshot)
}
