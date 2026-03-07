import test from 'node:test';
import assert from 'node:assert/strict';
import { runSimulation } from '../client/src/simulation/simulationEngine.ts';

test('simulation: ONU on short path gets OK status and rxPower', () => {
  const nodes: any[] = [
    {
      id: 'olt-1',
      position: { x: 0, y: 0 },
      data: { label: 'OLT-1', type: 'OLT', status: 'OK' },
    },
    {
      id: 'onu-1',
      position: { x: 100, y: 0 },
      data: { label: 'ONU-1', type: 'ONU', status: 'FAILURE' },
    },
  ];

  const edges: any[] = [
    {
      id: 'link-1',
      source: 'olt-1',
      target: 'onu-1',
      data: { length: 1, status: 'OK' },
    },
  ];

  const result = runSimulation(nodes, edges);
  const onu = result.nodes.find((node) => node.id === 'onu-1');

  assert.ok(onu);
  assert.equal(onu?.data.status, 'OK');
  assert.ok(typeof onu?.data.rxPower === 'number');
});
