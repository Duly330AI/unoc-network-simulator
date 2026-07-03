package models

import "database/sql"

// HardwareModel mirrors backend.models_pkg.hardware.HardwareModel for traffic
// capacity resolution. Only the fields needed by B1 congestion are loaded here.
type HardwareModel struct {
	ID           int64           `db:"id"`
	DeviceType   DeviceType      `db:"device_type"`
	CapacityGbps sql.NullFloat64 `db:"capacity_gbps"`
}

// PortProfile mirrors backend.models_pkg.hardware.PortProfile for interface
// capacity resolution.
type PortProfile struct {
	ID              int64           `db:"id"`
	HardwareModelID int64           `db:"hardware_model_id"`
	Name            string          `db:"name"`
	SpeedGbps       sql.NullFloat64 `db:"speed_gbps"`
	Role            sql.NullString  `db:"role"`
	PortRole        sql.NullString  `db:"port_role"`
}
