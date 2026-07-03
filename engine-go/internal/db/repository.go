package db

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5"
	"github.com/rs/zerolog/log"
	"github.com/unoc/engine-go/internal/models"
)

// FetchAllDevices retrieves all devices from the database
func FetchAllDevices(ctx context.Context) ([]models.Device, error) {
	query := `
		SELECT id, name, type, status, provisioned, admin_override_status,
		       tx_power_dbm, sensitivity_min_dbm, insertion_loss_db, capacity,
		       signal_power_dbm, signal_margin_db, signal_status,
		       parent_container_id, slot_id, tariff_id, vrf_id, hardware_model_id
		FROM device
		ORDER BY id
	`

	rows, err := Pool.Query(ctx, query)
	if err != nil {
		return nil, fmt.Errorf("failed to query devices: %w", err)
	}
	defer rows.Close()

	devices, err := pgx.CollectRows(rows, pgx.RowToStructByName[models.Device])
	if err != nil {
		return nil, fmt.Errorf("failed to collect device rows: %w", err)
	}

	log.Debug().Int("count", len(devices)).Msg("Fetched devices from database")
	return devices, nil
}

// FetchAllLinks retrieves all links from the database
func FetchAllLinks(ctx context.Context) ([]models.Link, error) {
	query := `
		SELECT id, a_interface_id, b_interface_id, status, kind,
		       admin_override_status, protection_mode, length_km, physical_medium_id
		FROM link
		ORDER BY id
	`

	rows, err := Pool.Query(ctx, query)
	if err != nil {
		return nil, fmt.Errorf("failed to query links: %w", err)
	}
	defer rows.Close()

	links, err := pgx.CollectRows(rows, pgx.RowToStructByName[models.Link])
	if err != nil {
		return nil, fmt.Errorf("failed to collect link rows: %w", err)
	}

	log.Debug().Int("count", len(links)).Msg("Fetched links from database")
	return links, nil
}

// FetchAllInterfaces retrieves all interfaces from the database
func FetchAllInterfaces(ctx context.Context) ([]models.Interface, error) {
	query := `
		SELECT id, device_id, name, role, admin_status, capacity,
		       port_role, bridge_domain_id, profile_name, mac_address
		FROM interface
		ORDER BY id
	`

	rows, err := Pool.Query(ctx, query)
	if err != nil {
		return nil, fmt.Errorf("failed to query interfaces: %w", err)
	}
	defer rows.Close()

	interfaces, err := pgx.CollectRows(rows, pgx.RowToStructByName[models.Interface])
	if err != nil {
		return nil, fmt.Errorf("failed to collect interface rows: %w", err)
	}

	log.Debug().Int("count", len(interfaces)).Msg("Fetched interfaces from database")
	return interfaces, nil
}

// FetchAllTariffs retrieves all tariffs from the database
func FetchAllTariffs(ctx context.Context) ([]models.Tariff, error) {
	query := `
		SELECT id, name, max_up_mbps, max_down_mbps, technology
		FROM tariff
		ORDER BY id
	`

	rows, err := Pool.Query(ctx, query)
	if err != nil {
		return nil, fmt.Errorf("failed to query tariffs: %w", err)
	}
	defer rows.Close()

	tariffs, err := pgx.CollectRows(rows, pgx.RowToStructByName[models.Tariff])
	if err != nil {
		return nil, fmt.Errorf("failed to collect tariff rows: %w", err)
	}

	log.Debug().Int("count", len(tariffs)).Msg("Fetched tariffs from database")
	return tariffs, nil
}

// FetchAllHardwareModels retrieves hardware catalog rows used for effective device capacity.
func FetchAllHardwareModels(ctx context.Context) ([]models.HardwareModel, error) {
	query := `
		SELECT id, device_type, capacity_gbps
		FROM hardwaremodel
		ORDER BY id
	`

	rows, err := Pool.Query(ctx, query)
	if err != nil {
		return nil, fmt.Errorf("failed to query hardware models: %w", err)
	}
	defer rows.Close()

	hardwareModels, err := pgx.CollectRows(rows, pgx.RowToStructByName[models.HardwareModel])
	if err != nil {
		return nil, fmt.Errorf("failed to collect hardware model rows: %w", err)
	}

	log.Debug().Int("count", len(hardwareModels)).Msg("Fetched hardware models from database")
	return hardwareModels, nil
}

// FetchAllPortProfiles retrieves port catalog rows used for effective interface capacity.
func FetchAllPortProfiles(ctx context.Context) ([]models.PortProfile, error) {
	query := `
		SELECT id, hardware_model_id, name, speed_gbps, role, port_role
		FROM portprofile
		ORDER BY hardware_model_id, name
	`

	rows, err := Pool.Query(ctx, query)
	if err != nil {
		return nil, fmt.Errorf("failed to query port profiles: %w", err)
	}
	defer rows.Close()

	portProfiles, err := pgx.CollectRows(rows, pgx.RowToStructByName[models.PortProfile])
	if err != nil {
		return nil, fmt.Errorf("failed to collect port profile rows: %w", err)
	}

	log.Debug().Int("count", len(portProfiles)).Msg("Fetched port profiles from database")
	return portProfiles, nil
}
