# SIMULATION_ENGINE_SPEC.md

## Purpose
Define the browser simulation engine responsible for computing network state.

Location:
/client/src/simulation

Main file:
simulationEngine.ts

## Simulation Loop

Tick interval: 100ms

Implementation:
setInterval(simulationTick, 100)

Each tick performs:

1 build graph
2 compute paths
3 calculate optical signal
4 calculate traffic load
5 update device status

## Graph Model

Node:
device

Edge:
fiber link

Structure example:

Node {
 id
 type
 ports
}

Edge {
 source
 target
 length
}

## Pathfinding

Use Dijkstra algorithm.

Purpose:
discover path from OLT to ONU.

Return:
path nodes
total length

## Optical Simulation

loss =
fiber_length * 0.35 +
splitter_loss +
connector_loss

rx_power = tx_power - loss

## Status Rules

rx_power >= -27 → OK
-30 < rx_power < -27 → WARNING
rx_power <= -30 → FAILURE

## Traffic Model

ONU traffic demand:
traffic_demand_mbps

Aggregate upstream traffic.

Compute:
splitter_load
OLT utilization

Status rules:
<70% OK
70–90% WARNING
>90% CONGESTED

## Failure Handling

If link.status == DOWN:

rebuild graph
recompute paths

Unreachable ONU → OFFLINE

## Performance

Target scale:

3000 devices
5000 links

Simulation tick must complete in <100ms.