package main

import (
	"context"
	"database/sql"
	"fmt"
	"log"
	"strings"
	"sync"
	"time"

	_ "github.com/lib/pq"
	pb "github.com/unoc/engine-go/proto/port_summary"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/emptypb"
)

// Device represents a network device
type Device struct {
	ID          string
	Type        string
	Status      string
	Provisioned bool
	ParentID    *string
}

// Interface represents a network interface
type Interface struct {
	ID          string
	DeviceID    string
	Name        string
	PortRole    *string
	ProfileName *string
	AdminStatus string // From admin_status column
}

// Link represents a connection between two interfaces
type Link struct {
	ID           string
	AInterfaceID *string
	BInterfaceID *string
	Status       string
}

// PortSummaryService implements the gRPC service
type PortSummaryService struct {
	pb.UnimplementedPortSummaryServiceServer

	// In-memory state
	devices    map[string]*Device
	interfaces map[string]*Interface
	links      map[string]*Link

	// Precomputed data for performance
	ponOccupancy map[string]map[string]int // oltID -> ponInterfaceID -> count
	opticalPaths map[string]string         // ontID -> ponInterfaceID

	// Indexes for fast lookups
	deviceInterfaces map[string][]*Interface // deviceID -> interfaces
	interfaceLinks   map[string][]*Link      // interfaceID -> links

	mu sync.RWMutex
	db *sql.DB
}

// NewPortSummaryService creates a new service instance
func NewPortSummaryService(db *sql.DB) *PortSummaryService {
	return &PortSummaryService{
		devices:          make(map[string]*Device),
		interfaces:       make(map[string]*Interface),
		links:            make(map[string]*Link),
		ponOccupancy:     make(map[string]map[string]int),
		opticalPaths:     make(map[string]string),
		deviceInterfaces: make(map[string][]*Interface),
		interfaceLinks:   make(map[string][]*Link),
		db:               db,
	}
}

// LoadInitialState loads all data from database into memory
func (s *PortSummaryService) LoadInitialState() error {
	s.mu.Lock()
	defer s.mu.Unlock()

	log.Println("Loading initial state from database...")
	start := time.Now()
	s.resetStateLocked()

	// BATCH LOAD 1: All devices
	if err := s.loadDevices(); err != nil {
		return fmt.Errorf("failed to load devices: %w", err)
	}

	// BATCH LOAD 2: All interfaces
	if err := s.loadInterfaces(); err != nil {
		return fmt.Errorf("failed to load interfaces: %w", err)
	}

	// BATCH LOAD 3: All links
	if err := s.loadLinks(); err != nil {
		return fmt.Errorf("failed to load links: %w", err)
	}

	// Build indexes
	s.buildIndexes()

	// PRECOMPUTE: Optical paths and PON occupancy
	s.computeOpticalPaths()
	s.computePONOccupancy()

	elapsed := time.Since(start)
	log.Printf("Loaded %d devices, %d interfaces, %d links in %v\n",
		len(s.devices), len(s.interfaces), len(s.links), elapsed)

	return nil
}

func (s *PortSummaryService) resetStateLocked() {
	s.devices = make(map[string]*Device)
	s.interfaces = make(map[string]*Interface)
	s.links = make(map[string]*Link)
	s.ponOccupancy = make(map[string]map[string]int)
	s.opticalPaths = make(map[string]string)
	s.deviceInterfaces = make(map[string][]*Interface)
	s.interfaceLinks = make(map[string][]*Link)
}

// loadDevices loads all devices from database
func (s *PortSummaryService) loadDevices() error {
	query := `SELECT id, type, status, provisioned, parent_container_id FROM device`
	rows, err := s.db.Query(query)
	if err != nil {
		return err
	}
	defer rows.Close()

	for rows.Next() {
		dev := &Device{}
		if err := rows.Scan(&dev.ID, &dev.Type, &dev.Status, &dev.Provisioned, &dev.ParentID); err != nil {
			return err
		}
		s.devices[dev.ID] = dev
	}

	return rows.Err()
}

// loadInterfaces loads all interfaces from database
func (s *PortSummaryService) loadInterfaces() error {
	query := `SELECT id, device_id, name, port_role, profile_name, admin_status FROM interface`
	rows, err := s.db.Query(query)
	if err != nil {
		return err
	}
	defer rows.Close()

	for rows.Next() {
		iface := &Interface{}
		if err := rows.Scan(&iface.ID, &iface.DeviceID, &iface.Name, &iface.PortRole, &iface.ProfileName, &iface.AdminStatus); err != nil {
			return err
		}
		s.interfaces[iface.ID] = iface
	}

	return rows.Err()
}

// loadLinks loads all links from database
func (s *PortSummaryService) loadLinks() error {
	query := `SELECT id, a_interface_id, b_interface_id, status FROM link`
	rows, err := s.db.Query(query)
	if err != nil {
		return err
	}
	defer rows.Close()

	for rows.Next() {
		link := &Link{}
		if err := rows.Scan(&link.ID, &link.AInterfaceID, &link.BInterfaceID, &link.Status); err != nil {
			return err
		}
		s.links[link.ID] = link
	}

	return rows.Err()
}

// buildIndexes builds lookup indexes for fast queries
func (s *PortSummaryService) buildIndexes() {
	// Build device -> interfaces index
	for _, iface := range s.interfaces {
		s.deviceInterfaces[iface.DeviceID] = append(s.deviceInterfaces[iface.DeviceID], iface)
	}

	// Build interface -> links index
	for _, link := range s.links {
		if link.AInterfaceID != nil {
			s.interfaceLinks[*link.AInterfaceID] = append(s.interfaceLinks[*link.AInterfaceID], link)
		}
		if link.BInterfaceID != nil {
			s.interfaceLinks[*link.BInterfaceID] = append(s.interfaceLinks[*link.BInterfaceID], link)
		}
	}
}

// HealthCheck implements the health check endpoint
func (s *PortSummaryService) HealthCheck(ctx context.Context, req *emptypb.Empty) (*pb.HealthCheckResponse, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	return &pb.HealthCheckResponse{
		Healthy:          true,
		CachedDevices:    int32(len(s.devices)),
		CachedInterfaces: int32(len(s.interfaces)),
		CachedLinks:      int32(len(s.links)),
		Version:          "1.0.0",
	}, nil
}

// computeOccupancy computes the occupancy for a given interface
// based on its port role
func (s *PortSummaryService) computeOccupancy(iface *Interface) int32 {
	s.mu.RLock()
	defer s.mu.RUnlock()

	// Default to 0 if port_role is nil
	if iface.PortRole == nil {
		return 0
	}

	portRole := *iface.PortRole

	switch portRole {
	case "PON":
		// PON port: Count provisioned ONTs on this PON port
		if ponMap, exists := s.ponOccupancy[iface.DeviceID]; exists {
			if count, ok := ponMap[iface.ID]; ok {
				return int32(count)
			}
		}
		return 0

	case "ACCESS":
		// ACCESS port: Count connected links
		links := s.interfaceLinks[iface.ID]
		return int32(len(links))

	case "UPLINK":
		// UPLINK port: Binary (0 or 1)
		links := s.interfaceLinks[iface.ID]
		if len(links) > 0 {
			return 1
		}
		return 0

	default:
		// Other port types: Return 0
		return 0
	}
}

// computeOpticalPaths computes the optical path from each ONT to its parent PON interface
// Uses BFS to traverse from ONT interface through links to find the PON port
func (s *PortSummaryService) computeOpticalPaths() {
	s.opticalPaths = make(map[string]string)

	// Find all ONT devices
	ontCount := 0
	for _, device := range s.devices {
		if !strings.EqualFold(device.Type, "ONT") {
			continue
		}
		ontCount++

		// Get ONT's optical interface (typically first interface)
		interfaces := s.deviceInterfaces[device.ID]
		if len(interfaces) == 0 {
			log.Printf("ONT %s has no interfaces in deviceInterfaces map\n", device.ID)
			continue
		}

		// Find optical interface (port_role = nil for ONT's optical port)
		var opticalInterface *Interface
		for _, iface := range interfaces {
			// ONT optical interface typically has no port_role or port_role = "OPTICAL"
			if iface.PortRole == nil || *iface.PortRole == "OPTICAL" {
				opticalInterface = iface
				break
			}
		}

		if opticalInterface == nil {
			// Fallback: Use first interface
			opticalInterface = interfaces[0]
		}

		// BFS to find PON interface
		ponInterfaceID := s.traceToPON(opticalInterface.ID)
		if ponInterfaceID != "" {
			s.opticalPaths[device.ID] = ponInterfaceID
		} else {
			log.Printf("ONT %s: No PON interface found from %s\n", device.ID, opticalInterface.ID)
		}
	}

	log.Printf("Found %d ONT devices, computed optical paths for %d ONTs\n", ontCount, len(s.opticalPaths))
}

// traceToPON performs BFS from an interface to find the connected PON interface
func (s *PortSummaryService) traceToPON(startInterfaceID string) string {
	visited := make(map[string]bool)
	queue := []string{startInterfaceID}
	visited[startInterfaceID] = true

	for len(queue) > 0 {
		currentIfaceID := queue[0]
		queue = queue[1:]

		currentIface := s.interfaces[currentIfaceID]
		if currentIface == nil {
			continue
		}

		// Check if this is a PON interface
		if currentIface.PortRole != nil && *currentIface.PortRole == "PON" {
			return currentIfaceID
		}

		// Traverse connected links
		links := s.interfaceLinks[currentIfaceID]
		for _, link := range links {
			// Get peer interface
			var peerInterfaceID string
			if link.AInterfaceID != nil && *link.AInterfaceID == currentIfaceID && link.BInterfaceID != nil {
				peerInterfaceID = *link.BInterfaceID
			} else if link.BInterfaceID != nil && *link.BInterfaceID == currentIfaceID && link.AInterfaceID != nil {
				peerInterfaceID = *link.AInterfaceID
			}

			if peerInterfaceID != "" && !visited[peerInterfaceID] {
				visited[peerInterfaceID] = true
				queue = append(queue, peerInterfaceID)
			}
		}

		// CRITICAL: Also traverse other interfaces on the same device (for passive devices like ODF)
		// This allows the BFS to "pass through" passive devices
		siblingInterfaces := s.deviceInterfaces[currentIface.DeviceID]
		for _, siblingIface := range siblingInterfaces {
			if siblingIface.ID != currentIfaceID && !visited[siblingIface.ID] {
				visited[siblingIface.ID] = true
				queue = append(queue, siblingIface.ID)
			}
		}
	}

	return "" // No PON interface found
}

// computePONOccupancy computes the number of ONTs connected to each PON port
func (s *PortSummaryService) computePONOccupancy() {
	s.ponOccupancy = make(map[string]map[string]int)

	// Count ONTs per PON interface using optical paths
	for ontID, ponInterfaceID := range s.opticalPaths {
		ponInterface := s.interfaces[ponInterfaceID]
		if ponInterface == nil {
			continue
		}

		oltID := ponInterface.DeviceID

		// Initialize OLT map if not exists
		if s.ponOccupancy[oltID] == nil {
			s.ponOccupancy[oltID] = make(map[string]int)
		}

		// Only count provisioned ONTs
		ontDevice := s.devices[ontID]
		if ontDevice != nil && ontDevice.Provisioned {
			s.ponOccupancy[oltID][ponInterfaceID]++
		}
	}

	// Count total ONTs across all OLTs
	totalONTs := 0
	totalPONPorts := 0
	for _, ponMap := range s.ponOccupancy {
		totalPONPorts += len(ponMap)
		for _, count := range ponMap {
			totalONTs += count
		}
	}

	log.Printf("Computed PON occupancy: %d ONTs across %d PON ports on %d OLTs\n",
		totalONTs, totalPONPorts, len(s.ponOccupancy))
}

// GetPortSummary returns port summary for a single device
func (s *PortSummaryService) GetPortSummary(ctx context.Context, req *pb.DeviceRequest) (*pb.PortSummaryResponse, error) {
	if err := s.LoadInitialState(); err != nil {
		return nil, status.Errorf(codes.Internal, "failed to refresh topology state: %v", err)
	}

	s.mu.RLock()
	defer s.mu.RUnlock()

	if req.DeviceId == "" {
		return nil, status.Error(codes.InvalidArgument, "device_id is required")
	}

	return s.buildPortSummaryLocked(req.DeviceId), nil
}

func (s *PortSummaryService) buildPortSummaryLocked(deviceID string) *pb.PortSummaryResponse {
	// Get device to verify it exists
	device := s.devices[deviceID]
	if device == nil {
		return &pb.PortSummaryResponse{
			Interfaces: []*pb.InterfaceSummary{},
		}
	}

	// Get interfaces for the device (O(1) lookup thanks to index!)
	interfaces := s.deviceInterfaces[deviceID]
	if len(interfaces) == 0 {
		return &pb.PortSummaryResponse{
			Interfaces: []*pb.InterfaceSummary{},
		}
	}

	// Build interface summaries
	summaries := make([]*pb.InterfaceSummary, 0, len(interfaces))
	for _, iface := range interfaces {
		summary := &pb.InterfaceSummary{
			Id:              iface.ID,
			Name:            iface.Name,
			PortRole:        "",
			EffectiveStatus: iface.AdminStatus, // Use interface's admin_status field
			Occupancy:       s.computeOccupancy(iface),
		}

		// Set port role (convert *string to string)
		if iface.PortRole != nil {
			summary.PortRole = *iface.PortRole
		}

		// Set capacity based on port_role
		summary.Capacity = s.getCapacity(iface, summary.PortRole)

		summaries = append(summaries, summary)
	}

	return &pb.PortSummaryResponse{
		Interfaces: summaries,
	}
}

// getCapacity returns the capacity for an interface based on its port_role
func (s *PortSummaryService) getCapacity(iface *Interface, portRole string) *int32 {
	switch portRole {
	case "PON":
		// PON ports typically support 128 ONTs (GPON standard)
		// Could be extended to read from catalog based on profile_name
		capacity := int32(128)
		return &capacity

	case "ACCESS":
		// ACCESS ports typically support 1 connection per port
		capacity := int32(1)
		return &capacity

	case "UPLINK":
		// UPLINK ports don't have a fixed capacity (link aggregation)
		return nil

	case "MANAGEMENT":
		// MGMT ports don't track occupancy
		return nil

	default:
		return nil
	}
}

// GetBulkPortSummary returns port summaries for multiple devices
func (s *PortSummaryService) GetBulkPortSummary(ctx context.Context, req *pb.BulkDeviceRequest) (*pb.BulkPortSummaryResponse, error) {
	if err := s.LoadInitialState(); err != nil {
		return nil, status.Errorf(codes.Internal, "failed to refresh topology state: %v", err)
	}

	s.mu.RLock()
	defer s.mu.RUnlock()

	result := make(map[string]*pb.PortSummaryResponse)

	for _, deviceID := range req.DeviceIds {
		result[deviceID] = s.buildPortSummaryLocked(deviceID)
	}

	return &pb.BulkPortSummaryResponse{
		Summaries: result,
	}, nil
}

// InvalidateCache invalidates cache for a device (placeholder for Phase 2)
func (s *PortSummaryService) InvalidateCache(ctx context.Context, req *pb.InvalidateCacheRequest) (*emptypb.Empty, error) {
	// TODO: Phase 2 - Implement event-driven cache invalidation
	log.Printf("InvalidateCache called for device %s (not implemented yet)\n", req.DeviceId)
	return &emptypb.Empty{}, nil
}
