import { create } from 'zustand';
import {
  Connection,
  Edge,
  EdgeChange,
  Node,
  NodeChange,
  OnNodesChange,
  OnEdgesChange,
  OnConnect,
  applyNodeChanges,
  applyEdgeChanges,
} from 'reactflow';
import { io, Socket } from 'socket.io-client';

export type DeviceType = 'OLT' | 'Splitter' | 'ONU' | 'Switch' | 'PatchPanel' | 'Amplifier';

export interface DeviceData {
  label: string;
  type: DeviceType;
  status: 'OK' | 'WARNING' | 'FAILURE' | 'OFFLINE';
  rxPower?: number;
  trafficLoad?: number;
  ports?: Array<{ id: string; portNumber: number; portType: string; status: string }>;
}

export interface LinkData {
  length?: number;
  fiberLength: number;
  fiberType?: string;
  status: 'OK' | 'BROKEN';
}

interface TopologyResponse {
  nodes: Array<{
    id: string;
    position: { x: number; y: number };
    data: {
      name: string;
      type: DeviceType | string;
      status: DeviceData['status'];
      ports?: DeviceData['ports'];
    };
  }>;
  edges: Array<{
    id: string;
    source: string;
    target: string;
    sourceHandle: string;
    targetHandle: string;
    data: {
      fiberLength: number;
      fiberType?: string;
      status: LinkData['status'];
    };
  }>;
}

interface AppState {
  nodes: Node<DeviceData>[];
  edges: Edge<LinkData>[];
  socketInitialized: boolean;
  onNodesChange: OnNodesChange;
  onEdgesChange: OnEdgesChange;
  onConnect: OnConnect;
  updateNodeData: (id: string, data: Partial<DeviceData>) => void;
  updateEdgeData: (id: string, data: Partial<LinkData>) => void;
  setNodes: (nodes: Node<DeviceData>[]) => void;
  setEdges: (edges: Edge<LinkData>[]) => void;
  fetchTopology: () => Promise<void>;
  createDevice: (device: { name: string; type: DeviceType; x: number; y: number }) => Promise<void>;
  createLink: (
    sourceId: string,
    targetId: string,
    sourcePortId: string,
    targetPortId: string
  ) => Promise<void>;
  initializeSocket: () => void;
}

const socket: Socket = io();

const normalizeDeviceType = (rawType: string): DeviceType => {
  if (rawType === 'ONT') return 'ONU';
  if (rawType === 'SPLITTER') return 'Splitter';
  if (rawType === 'SWITCH' || rawType === 'ROUTER') return 'Switch';
  if (rawType === 'ODF' || rawType === 'PATCHPANEL') return 'PatchPanel';
  if (rawType === 'AMPLIFIER') return 'Amplifier';
  if (rawType === 'OLT' || rawType === 'Splitter' || rawType === 'ONU' || rawType === 'Switch' || rawType === 'PatchPanel' || rawType === 'Amplifier') {
    return rawType;
  }
  return 'Switch';
};

const mapTopologyNode = (node: TopologyResponse['nodes'][number]): Node<DeviceData> => ({
  id: node.id,
  type: 'default',
  position: node.position,
  data: {
    label: node.data.name,
    type: normalizeDeviceType(node.data.type),
    status: node.data.status,
    ports: node.data.ports,
  },
});

const mapTopologyEdge = (edge: TopologyResponse['edges'][number]): Edge<LinkData> => ({
  id: edge.id,
  source: edge.source,
  target: edge.target,
  sourceHandle: edge.sourceHandle,
  targetHandle: edge.targetHandle,
  type: 'smoothstep',
  data: {
    length: edge.data.fiberLength,
    fiberLength: edge.data.fiberLength,
    fiberType: edge.data.fiberType,
    status: edge.data.status,
  },
});

export const useStore = create<AppState>((set, get) => ({
  nodes: [],
  edges: [],
  socketInitialized: false,

  onNodesChange: (changes: NodeChange[]) => {
    set({
      nodes: applyNodeChanges(changes, get().nodes) as Node<DeviceData>[],
    });
  },

  onEdgesChange: (changes: EdgeChange[]) => {
    set({
      edges: applyEdgeChanges(changes, get().edges) as Edge<LinkData>[],
    });
  },

  onConnect: async (connection: Connection) => {
    if (connection.source && connection.target && connection.sourceHandle && connection.targetHandle) {
      await get().createLink(connection.source, connection.target, connection.sourceHandle, connection.targetHandle);
    }
  },

  updateNodeData: (id: string, data: Partial<DeviceData>) => {
    set({
      nodes: get().nodes.map((node) => {
        if (node.id === id) {
          return { ...node, data: { ...node.data, ...data } as DeviceData };
        }
        return node;
      }),
    });
  },

  updateEdgeData: (id: string, data: Partial<LinkData>) => {
    set({
      edges: get().edges.map((edge) => {
        if (edge.id === id) {
          return { ...edge, data: { ...edge.data, ...data } as LinkData };
        }
        return edge;
      }),
    });
  },

  setNodes: (nodes) => set({ nodes }),
  setEdges: (edges) => set({ edges }),

  fetchTopology: async () => {
    try {
      const res = await fetch('/api/topology');
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const data = (await res.json()) as TopologyResponse;
      set({
        nodes: data.nodes.map(mapTopologyNode),
        edges: data.edges.map(mapTopologyEdge),
      });
    } catch (error) {
      console.error('Failed to fetch topology:', error);
    }
  },

  createDevice: async (device) => {
    try {
      const res = await fetch('/api/devices', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(device),
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
    } catch (error) {
      console.error('Failed to create device:', error);
    }
  },

  createLink: async (sourceId, targetId, sourcePortId, targetPortId) => {
    try {
      const res = await fetch('/api/links', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sourceId, targetId, sourcePortId, targetPortId }),
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
    } catch (error) {
      console.error('Failed to create link:', error);
    }
  },

  initializeSocket: () => {
    if (get().socketInitialized) {
      return;
    }

    socket.on('device:created', (device: any) => {
      const newNode: Node<DeviceData> = {
        id: device.id,
        type: 'default',
        position: { x: device.x, y: device.y },
        data: {
          label: device.name,
          type: normalizeDeviceType(device.type),
          status: device.status,
          ports: device.ports,
        },
      };

      set((state) => ({ nodes: [...state.nodes, newNode] }));
    });

    socket.on('device:updated', (device: any) => {
      set((state) => ({
        nodes: state.nodes.map((node) =>
          node.id === device.id
            ? {
                ...node,
                position: { x: device.x, y: device.y },
                data: {
                  ...node.data,
                  label: device.name,
                  type: normalizeDeviceType(device.type),
                  status: device.status,
                  ports: device.ports,
                },
              }
            : node
        ),
      }));
    });

    socket.on('link:created', (link: any) => {
      const newEdge: Edge<LinkData> = {
        id: link.id,
        source: link.sourcePort.deviceId,
        target: link.targetPort.deviceId,
        sourceHandle: link.sourcePortId,
        targetHandle: link.targetPortId,
        type: 'smoothstep',
        data: {
          length: link.fiberLength,
          fiberLength: link.fiberLength,
          fiberType: link.fiberType,
          status: link.status,
        },
      };

      set((state) => ({ edges: [...state.edges, newEdge] }));
    });

    socket.on('device:deleted', ({ id }: { id: string }) => {
      set((state) => ({
        nodes: state.nodes.filter((node) => node.id !== id),
        edges: state.edges.filter((edge) => edge.source !== id && edge.target !== id),
      }));
    });

    socket.on('link:deleted', ({ id }: { id: string }) => {
      set((state) => ({ edges: state.edges.filter((edge) => edge.id !== id) }));
    });

    socket.on('device:metrics', (updates: Array<{ id: string; trafficLoad: number; rxPower: number; status?: DeviceData['status'] }>) => {
      set((state) => ({
        nodes: state.nodes.map((node) => {
          const update = updates.find((candidate) => candidate.id === node.id);
          if (!update) {
            return node;
          }

          return {
            ...node,
            data: {
              ...node.data,
              trafficLoad: update.trafficLoad,
              rxPower: update.rxPower,
              status: update.status ?? node.data.status,
            },
          };
        }),
      }));
    });

    socket.on('device:status', ({ id, status }: { id: string; status: DeviceData['status'] }) => {
      set((state) => ({
        nodes: state.nodes.map((node) =>
          node.id === id
            ? {
                ...node,
                data: {
                  ...node.data,
                  status,
                },
              }
            : node
        ),
      }));
    });

    set({ socketInitialized: true });
  },
}));
