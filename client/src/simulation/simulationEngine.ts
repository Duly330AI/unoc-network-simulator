import { Node, Edge } from 'reactflow';
import { DeviceData, LinkData } from '../store/useStore';

// Constants
const FIBER_LOSS_PER_KM = 0.35; // dB/km
const CONNECTOR_LOSS = 0.2; // dB
const SPLITTER_LOSS: Record<string, number> = {
  '1:2': 3.5,
  '1:4': 7.2,
  '1:8': 10.5,
  '1:16': 13.5,
  '1:32': 17.0,
};

// Helper to get splitter loss based on type (simplified for now, assuming standard splitters)
// In a real app, splitter type would be a property of the device.
const getSplitterLoss = (type: string): number => {
  // For simplicity, let's assume all splitters are 1:4 for now unless specified
  return SPLITTER_LOSS['1:4'];
};

export const runSimulation = (
  nodes: Node<DeviceData>[],
  edges: Edge<LinkData>[]
): { nodes: Node<DeviceData>[]; edges: Edge<LinkData>[] } => {
  const newNodes = [...nodes];
  const newEdges = [...edges];

  // 1. Build Graph (Adjacency List)
  const adj: Record<string, { target: string; edgeId: string }[]> = {};
  edges.forEach((edge) => {
    if (!adj[edge.source]) adj[edge.source] = [];
    adj[edge.source].push({ target: edge.target, edgeId: edge.id });
  });

  // 2. Find OLTs (Source nodes)
  const olts = newNodes.filter((n) => n.data.type === 'OLT');

  // 3. Propagate Signal (BFS/DFS)
  // Initialize all nodes with -Infinity power (except OLT)
  const signalPower: Record<string, number> = {};
  
  olts.forEach((olt) => {
    signalPower[olt.id] = 3; // Starting power +3 dBm
  });

  const queue = [...olts.map((n) => n.id)];
  const visited = new Set<string>();

  while (queue.length > 0) {
    const u = queue.shift()!;
    if (visited.has(u)) continue;
    visited.add(u);

    const currentPower = signalPower[u];
    const neighbors = adj[u] || [];

    neighbors.forEach(({ target, edgeId }) => {
      const edge = newEdges.find((e) => e.id === edgeId)!;
      const targetNode = newNodes.find((n) => n.id === target)!;

      // Calculate loss
      let loss = (edge.data?.length || 1) * FIBER_LOSS_PER_KM + CONNECTOR_LOSS;
      
      if (targetNode.data.type === 'Splitter') {
        loss += getSplitterLoss('1:4'); // Assume 1:4 splitter loss for the node itself or outgoing?
        // Usually splitter loss is on the output ports.
        // Let's apply it to the link for simplicity or node processing.
        // Better: Apply splitter loss when traversing *through* a splitter.
        // Here we are arriving at the splitter.
      }

      // If source was a splitter, we already applied loss?
      // Let's refine:
      // OLT -> Splitter (loss = fiber + connector)
      // Splitter -> ONU (loss = fiber + connector + splitter_insertion_loss)
      
      const sourceNode = newNodes.find((n) => n.id === u)!;
      if (sourceNode.data.type === 'Splitter') {
         loss += getSplitterLoss('1:4');
      }

      const receivedPower = currentPower - loss;
      
      // Update target power if better signal found (or just first path)
      if (signalPower[target] === undefined || receivedPower > signalPower[target]) {
        signalPower[target] = receivedPower;
        queue.push(target);
      }
    });
  }

  // 4. Update Node Status based on Signal
  newNodes.forEach((node) => {
    if (node.data.type === 'ONU') {
      const power = signalPower[node.id];
      let status: 'OK' | 'WARNING' | 'FAILURE' = 'FAILURE';
      
      if (power !== undefined) {
        if (power >= -27) status = 'OK';
        else if (power >= -30) status = 'WARNING';
        else status = 'FAILURE';
      }

      node.data = {
        ...node.data,
        rxPower: power !== undefined ? parseFloat(power.toFixed(2)) : -99,
        status,
      };
    } else {
       // For non-ONUs, status is OK if reachable?
       node.data = { ...node.data, status: 'OK' };
    }
  });

  return { nodes: newNodes, edges: newEdges };
};
