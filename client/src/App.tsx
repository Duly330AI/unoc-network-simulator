import React, { useCallback, useEffect, useRef } from 'react';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  ReactFlowProvider,
  Panel,
  useReactFlow,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { useStore, DeviceType } from './store/useStore';
import { Server, Split, Monitor, Activity } from 'lucide-react';

const DeviceIcon = ({ type }: { type: DeviceType }) => {
  switch (type) {
    case 'OLT': return <Server className="w-6 h-6 text-blue-600" />;
    case 'Splitter': return <Split className="w-6 h-6 text-orange-500" />;
    case 'ONU': return <Monitor className="w-6 h-6 text-green-600" />;
    default: return <Activity className="w-6 h-6 text-gray-500" />;
  }
};

const Sidebar = () => {
  const onDragStart = (event: React.DragEvent, nodeType: DeviceType) => {
    event.dataTransfer.setData('application/reactflow', nodeType);
    event.dataTransfer.effectAllowed = 'move';
  };

  return (
    <aside className="w-64 bg-white border-r border-gray-200 p-4 flex flex-col gap-4">
      <h2 className="text-lg font-bold text-gray-800">Devices</h2>
      <div className="flex flex-col gap-2">
        {['OLT', 'Splitter', 'ONU', 'Switch'].map((type) => (
          <div
            key={type}
            className="flex items-center gap-2 p-2 bg-gray-50 border border-gray-200 rounded cursor-grab hover:bg-gray-100"
            onDragStart={(event) => onDragStart(event, type as DeviceType)}
            draggable
          >
            <DeviceIcon type={type as DeviceType} />
            <span>{type}</span>
          </div>
        ))}
      </div>
      <div className="mt-auto">
        <h3 className="text-sm font-semibold text-gray-500">Status</h3>
        <div className="flex items-center gap-2 mt-2">
          <div className="w-3 h-3 rounded-full bg-green-500"></div>
          <span className="text-sm">Connected to Backend</span>
        </div>
      </div>
    </aside>
  );
};

const Flow = () => {
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const { project } = useReactFlow();
  const {
    nodes,
    edges,
    onNodesChange,
    onEdgesChange,
    onConnect,
    fetchTopology,
    initializeSocket,
    createDevice,
  } = useStore();

  useEffect(() => {
    initializeSocket();
    fetchTopology();
  }, [fetchTopology, initializeSocket]);

  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();

      const type = event.dataTransfer.getData('application/reactflow') as DeviceType;

      if (typeof type === 'undefined' || !type) {
        return;
      }

      const reactFlowBounds = reactFlowWrapper.current!.getBoundingClientRect();
      const position = project({
        x: event.clientX - reactFlowBounds.left,
        y: event.clientY - reactFlowBounds.top,
      });

      createDevice({
        name: `${type}-${Date.now()}`,
        type,
        x: position.x,
        y: position.y,
      });
    },
    [createDevice, project]
  );

  return (
    <div className="flex h-screen w-screen">
      <Sidebar />
      <div className="flex-1 h-full bg-gray-50" ref={reactFlowWrapper}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onDrop={onDrop}
          onDragOver={onDragOver}
          fitView
        >
          <Controls />
          <MiniMap />
          <Background gap={12} size={1} />
          <Panel position="top-right" className="bg-white p-2 rounded shadow-sm border border-gray-200">
             <div className="text-xs text-gray-500">
                Nodes: {nodes.length} | Edges: {edges.length}
             </div>
          </Panel>
        </ReactFlow>
      </div>
    </div>
  );
};

export default function App() {
  return (
    <ReactFlowProvider>
      <Flow />
    </ReactFlowProvider>
  );
}
