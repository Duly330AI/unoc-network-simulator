import test from 'node:test';
import assert from 'node:assert/strict';
import request from 'supertest';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

process.env.NODE_ENV = 'test';
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const prismaDir = path.resolve(__dirname, '../prisma');
const seedDb = path.join(prismaDir, 'dev.db');
const testDb = path.join(prismaDir, 'test.db');

if (!fs.existsSync(testDb)) {
  fs.copyFileSync(seedDb, testDb);
}

process.env.DATABASE_URL = `file:${testDb}`;

const { app, prisma, stopTrafficLoop } = await import('../server.ts');

test.beforeEach(async () => {
  await prisma.link.deleteMany();
  await prisma.port.deleteMany();
  await prisma.device.deleteMany();
  await prisma.network.deleteMany();
});

test.after(async () => {
  stopTrafficLoop();
  await prisma.$disconnect();
  if (fs.existsSync(testDb)) {
    fs.rmSync(testDb);
  }
});

test('API smoke: create device, create link, fetch topology', async () => {
  const oltRes = await request(app).post('/api/devices').send({
    name: 'OLT-1',
    type: 'OLT',
    x: 100,
    y: 100,
  });
  assert.equal(oltRes.status, 201);

  const onuRes = await request(app).post('/api/devices').send({
    name: 'ONU-1',
    type: 'ONU',
    x: 250,
    y: 150,
  });
  assert.equal(onuRes.status, 201);

  const oltPonPort = oltRes.body.ports.find((port: any) => port.portType === 'PON');
  const onuPonPort = onuRes.body.ports.find((port: any) => port.portType === 'PON');

  assert.ok(oltPonPort?.id);
  assert.ok(onuPonPort?.id);

  const linkRes = await request(app).post('/api/links').send({
    sourcePortId: oltPonPort.id,
    targetPortId: onuPonPort.id,
  });
  assert.equal(linkRes.status, 201);

  const topologyRes = await request(app).get('/api/topology');
  assert.equal(topologyRes.status, 200);
  assert.equal(topologyRes.body.nodes.length, 2);
  assert.equal(topologyRes.body.edges.length, 1);
});
