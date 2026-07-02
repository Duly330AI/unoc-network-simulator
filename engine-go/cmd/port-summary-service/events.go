package main

import (
	"context"
	"database/sql"
	"fmt"
	"log"
	"os"
	"strings"
	"time"

	"github.com/lib/pq"
)

// EventType represents the type of database event
type EventType string

const (
	EventLinkCreated    EventType = "link_created"
	EventLinkDeleted    EventType = "link_deleted"
	EventLinkUpdated    EventType = "link_updated"
	EventDeviceCreated  EventType = "device_created"
	EventDeviceUpdated  EventType = "device_updated"
	EventDeviceDeleted  EventType = "device_deleted"
	EventTopologyChange EventType = "topology_version_change"
)

// StartEventListener starts listening for PostgreSQL NOTIFY events
func (s *PortSummaryService) StartEventListener(ctx context.Context) error {
	log.Println("Starting PostgreSQL NOTIFY event listener...")

	// Get DATABASE_URL from environment (same as main service)
	dbURL := ""
	// We need to extract the connection string from the *sql.DB
	// For now, get it from environment variable
	if dbEnv := os.Getenv("DATABASE_URL"); dbEnv != "" {
		dbURL = dbEnv
	} else {
		return fmt.Errorf("DATABASE_URL not set for event listener")
	}

	listener := pq.NewListener(
		dbURL,
		10*time.Second, // minReconnectInterval
		time.Minute,    // maxReconnectInterval
		func(ev pq.ListenerEventType, err error) {
			if err != nil {
				log.Printf("PostgreSQL listener error: %v", err)
			}
			switch ev {
			case pq.ListenerEventConnected:
				log.Println("✅ PostgreSQL NOTIFY listener connected")
			case pq.ListenerEventDisconnected:
				log.Println("⚠️  PostgreSQL NOTIFY listener disconnected, reconnecting...")
			case pq.ListenerEventReconnected:
				log.Println("✅ PostgreSQL NOTIFY listener reconnected")
			case pq.ListenerEventConnectionAttemptFailed:
				log.Printf("❌ PostgreSQL NOTIFY connection attempt failed: %v", err)
			}
		},
	)

	// Listen to relevant channels
	if err := listener.Listen("link_events"); err != nil {
		return err
	}
	if err := listener.Listen("device_events"); err != nil {
		return err
	}
	if err := listener.Listen("topology_events"); err != nil {
		return err
	}

	log.Println("Listening to PostgreSQL channels: link_events, device_events, topology_events")

	// Event processing goroutine
	go func() {
		for {
			select {
			case <-ctx.Done():
				log.Println("Stopping event listener...")
				listener.Close()
				return

			case notification := <-listener.Notify:
				if notification == nil {
					// Connection lost, listener will reconnect automatically
					continue
				}

				// Process event
				s.handleEvent(notification.Channel, notification.Extra)

			case <-time.After(90 * time.Second):
				// Ping every 90s to keep connection alive
				if err := listener.Ping(); err != nil {
					log.Printf("Listener ping failed: %v", err)
				}
			}
		}
	}()

	return nil
}

// handleEvent processes incoming PostgreSQL NOTIFY events
func (s *PortSummaryService) handleEvent(channel string, payload string) {
	log.Printf("📩 Event received: channel=%s payload=%s", channel, payload)

	switch channel {
	case "link_events":
		s.handleLinkEvent(payload)

	case "device_events":
		s.handleDeviceEvent(payload)

	case "topology_events":
		if eventType, _ := parseEventPayload(payload); EventType(eventType) == EventTopologyChange {
			log.Println("🔄 Topology version changed, performing full reload...")
			if err := s.LoadInitialState(); err != nil {
				log.Printf("❌ Full reload failed: %v", err)
			} else {
				log.Println("✅ Full reload completed")
			}
		}

	default:
		log.Printf("Unknown event channel: %s", channel)
	}
}

func parseEventPayload(payload string) (string, string) {
	parts := strings.SplitN(payload, ":", 2)
	eventType := strings.TrimSpace(parts[0])
	if len(parts) == 1 {
		return eventType, ""
	}
	return eventType, strings.TrimSpace(parts[1])
}

func (s *PortSummaryService) reloadAllForEvent(eventLabel string) {
	log.Printf("🔄 %s received, performing full topology reload", eventLabel)
	if err := s.LoadInitialState(); err != nil {
		log.Printf("❌ Full reload failed after %s: %v", eventLabel, err)
		return
	}
	log.Printf("✅ Full reload completed after %s", eventLabel)
}

// handleLinkEvent processes link creation/deletion events
func (s *PortSummaryService) handleLinkEvent(payload string) {
	// Parse payload format: "link_created:LINK-001" or "link_deleted:LINK-001"
	eventType, linkID := parseEventPayload(payload)
	if eventType == "" {
		log.Printf("Failed to parse link event payload: %s", payload)
		return
	}

	switch EventType(eventType) {
	case EventLinkCreated, EventLinkUpdated, EventLinkDeleted:
		if linkID == "" {
			log.Printf("Link event %s had no link id; refreshing all topology", eventType)
		}
		s.reloadAllForEvent(eventType)

	default:
		log.Printf("Unknown link event type: %s", eventType)
	}
}

// handleDeviceEvent processes device provisioning events
func (s *PortSummaryService) handleDeviceEvent(payload string) {
	// Parse payload format: "device_provisioned:DEV-001" or "device_deleted:DEV-001"
	eventType, deviceID := parseEventPayload(payload)
	if eventType == "" {
		log.Printf("Failed to parse device event payload: %s", payload)
		return
	}

	switch EventType(eventType) {
	case EventDeviceCreated, EventDeviceUpdated:
		if deviceID == "" {
			log.Printf("Device event %s had no device id; refreshing all topology", eventType)
		}
		s.reloadAllForEvent(eventType)

	case EventDeviceDeleted:
		if deviceID == "" {
			log.Printf("Device delete event had no device id; refreshing all topology")
		}
		s.reloadAllForEvent(eventType)

	default:
		log.Printf("Unknown device event type: %s", eventType)
	}
}

// reloadLink reloads a single link from database and updates cache
func (s *PortSummaryService) reloadLink(linkID string) {
	query := `SELECT id, a_interface_id, b_interface_id, status FROM link WHERE id = $1`

	link := &Link{}
	err := s.db.QueryRow(query, linkID).Scan(
		&link.ID, &link.AInterfaceID, &link.BInterfaceID, &link.Status,
	)

	if err == sql.ErrNoRows {
		log.Printf("⚠️  Link %s not found in database (might be deleted)", linkID)
		return
	}
	if err != nil {
		log.Printf("❌ Failed to reload link %s: %v", linkID, err)
		return
	}

	// Update cache
	s.mu.Lock()
	s.links[linkID] = link
	s.mu.Unlock()

	log.Printf("🔄 Link %s reloaded", linkID)

	// Recompute affected OLTs (ONT links changed)
	s.recomputeAffectedOLTs(linkID)
}

// reloadDevice reloads a single device and its interfaces from database
func (s *PortSummaryService) reloadDevice(deviceID string) {
	// Reload device
	devQuery := `SELECT id, type, status, provisioned, parent_container_id FROM device WHERE id = $1`
	dev := &Device{}
	err := s.db.QueryRow(devQuery, deviceID).Scan(
		&dev.ID, &dev.Type, &dev.Status, &dev.Provisioned, &dev.ParentID,
	)

	if err == sql.ErrNoRows {
		log.Printf("⚠️  Device %s not found in database (might be deleted)", deviceID)
		return
	}
	if err != nil {
		log.Printf("❌ Failed to reload device %s: %v", deviceID, err)
		return
	}

	// Reload device interfaces
	ifaceQuery := `SELECT id, device_id, name, port_role, profile_name, admin_status FROM interface WHERE device_id = $1`
	rows, err := s.db.Query(ifaceQuery, deviceID)
	if err != nil {
		log.Printf("❌ Failed to reload interfaces for device %s: %v", deviceID, err)
		return
	}
	defer rows.Close()

	interfaces := []*Interface{}
	for rows.Next() {
		iface := &Interface{}
		if err := rows.Scan(&iface.ID, &iface.DeviceID, &iface.Name, &iface.PortRole, &iface.ProfileName, &iface.AdminStatus); err != nil {
			log.Printf("❌ Failed to scan interface: %v", err)
			continue
		}
		interfaces = append(interfaces, iface)
	}

	// Update cache
	s.mu.Lock()
	s.devices[deviceID] = dev
	s.deviceInterfaces[deviceID] = interfaces
	for _, iface := range interfaces {
		s.interfaces[iface.ID] = iface
	}
	s.mu.Unlock()

	log.Printf("🔄 Device %s reloaded with %d interfaces", deviceID, len(interfaces))

	// If ONT device, recompute optical path
	if dev.Type == "ont" {
		s.recomputeOpticalPathForONT(deviceID)
	}
}

// recomputeAffectedOLTs recomputes PON occupancy for OLTs affected by link change
func (s *PortSummaryService) recomputeAffectedOLTs(linkID string) {
	// For now, do a full PON occupancy recompute (fast enough for production)
	// TODO: Optimize to only recompute affected OLTs
	s.mu.Lock()
	defer s.mu.Unlock()

	s.computePONOccupancy()
	log.Println("✅ PON occupancy recomputed")
}

// recomputeOpticalPathForONT recomputes optical path for a single ONT
func (s *PortSummaryService) recomputeOpticalPathForONT(ontID string) {
	s.mu.Lock()
	defer s.mu.Unlock()

	// Simple optical path finder: trace from ONT upward through links
	dev, exists := s.devices[ontID]
	if !exists || dev.Type != "ont" {
		return
	}

	// Find PON interface connected to this ONT
	for _, iface := range s.deviceInterfaces[ontID] {
		if iface.PortRole != nil && *iface.PortRole == "pon_downlink" {
			// Find link on this interface
			for _, link := range s.interfaceLinks[iface.ID] {
				// Find peer interface (OLT PON port)
				var peerIfaceID string
				if link.AInterfaceID != nil && *link.AInterfaceID == iface.ID {
					if link.BInterfaceID != nil {
						peerIfaceID = *link.BInterfaceID
					}
				} else if link.BInterfaceID != nil && *link.BInterfaceID == iface.ID {
					if link.AInterfaceID != nil {
						peerIfaceID = *link.AInterfaceID
					}
				}

				if peerIfaceID != "" {
					s.opticalPaths[ontID] = peerIfaceID
					log.Printf("🔄 Optical path for ONT %s: %s", ontID, peerIfaceID)
					return
				}
			}
		}
	}
}
