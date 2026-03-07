# MASTER_SPEC_UNOC_LITE.md

> Archive Note (2026-03-07): Dieses Dokument ist nur noch High-Level-Grundgerüst.\
> Operativer Source-of-Truth ist `docs/ROADMAP.md` plus die Fachdokumente `docs/01..13`.

## Project Goal
Build a full-stack FTTH Network Live Simulator web application.

The application allows users to:
- visually design fiber network topologies
- simulate optical signal propagation
- simulate traffic load
- detect failures
- visualize device status in real time

Simulation runs entirely in the browser. Backend stores topology data.

## Stack
Frontend
- React
- TypeScript
- React Flow
- Tailwind CSS
- Zustand

Backend
- Node.js
- Express.js

Database
- SQLite
- Prisma ORM

## Project Structure
/unoc-simulator
  /server
    server.ts
    routes/
    services/
    prisma/
  /client
    src/
      components/
      simulation/
      store/
      pages/
  /shared/types

## Database Schema

### networks
id TEXT PRIMARY KEY
name TEXT
created_at DATETIME

### devices
id TEXT PRIMARY KEY
network_id TEXT
name TEXT
type TEXT
model TEXT
x INTEGER
y INTEGER
status TEXT

Device types:
OLT
Splitter
ONU
Switch
PatchPanel
Amplifier

### ports
id TEXT PRIMARY KEY
device_id TEXT
port_number INTEGER
port_type TEXT
status TEXT

### links
id TEXT PRIMARY KEY
source_port TEXT
target_port TEXT
fiber_length REAL
fiber_type TEXT
status TEXT

Fiber types:
SMF
MMF

## Simulation Loop
Simulation runs every 100 ms.

Cycle:
1 load topology
2 build graph
3 compute paths
4 compute signal
5 compute traffic
6 update device status
7 refresh UI

## Optical Signal Model

fiber_loss = 0.35 dB/km
connector_loss = 0.2 dB

Splitter loss:
1:2 = 3.5 dB
1:4 = 7.2 dB
1:8 = 10.5 dB
1:16 = 13.5 dB
1:32 = 17 dB

total_loss =
fiber_length * fiber_loss +
splitter_loss +
connector_loss

rx_power = tx_power - total_loss

Signal status:
>= -27 dBm OK
-30 to -27 WARNING
<= -30 FAILURE

## Traffic Model

ONU demand: traffic_demand_mbps

splitter_load = sum(ONU traffic)

olt_utilization =
sum(splitter_load) / olt_capacity

Status:
<70% OK
70–90% WARNING
>90% CONGESTED
