import "dotenv/config";
import express from "express";
import { createServer as createViteServer } from "vite";
import { createServer } from "http";
import { Server } from "socket.io";
import path from "path";
import { fileURLToPath } from "url";
import cors from "cors";
import { PrismaClient } from "@prisma/client";
import { z } from "zod";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

if (!process.env.DATABASE_URL) {
  process.env.DATABASE_URL = `file:${path.resolve(__dirname, "prisma/dev.db")}`;
} else if (process.env.DATABASE_URL.startsWith("file:./")) {
  process.env.DATABASE_URL = `file:${path.resolve(
    __dirname,
    "prisma",
    process.env.DATABASE_URL.slice("file:./".length)
  )}`;
}

const prisma = new PrismaClient();
const app = express();
const httpServer = createServer(app);
const io = new Server(httpServer, {
  cors: { origin: "*" },
});

const PORT = 3000;
const TRAFFIC_INTERVAL_MS = 1000;

const DOC_DEVICE_TYPES = ["OLT", "Splitter", "ONU", "Switch", "PatchPanel", "Amplifier"] as const;
type DocDeviceType = (typeof DOC_DEVICE_TYPES)[number];

const LEGACY_TYPE_MAP: Record<string, DocDeviceType> = {
  OLT: "OLT",
  ONU: "ONU",
  ONT: "ONU",
  SPLITTER: "Splitter",
  Splitter: "Splitter",
  SWITCH: "Switch",
  ROUTER: "Switch",
  ODF: "PatchPanel",
  PATCHPANEL: "PatchPanel",
  AMPLIFIER: "Amplifier",
};

const toDocDeviceType = (value: string): DocDeviceType | undefined => {
  return LEGACY_TYPE_MAP[value] ?? LEGACY_TYPE_MAP[value.toUpperCase()];
};

app.use(cors());
app.use(express.json());

const DeviceCreateSchema = z.object({
  name: z.string().min(1),
  type: z.string().transform((value, ctx) => {
    const mapped = toDocDeviceType(value);
    if (!mapped) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: `Invalid device type: ${value}`,
      });
      return z.NEVER;
    }
    return mapped;
  }),
  x: z.number(),
  y: z.number(),
  parentId: z.string().optional(),
});

const DevicePatchSchema = z
  .object({
    name: z.string().min(1).optional(),
    x: z.number().optional(),
    y: z.number().optional(),
    status: z.enum(["OK", "WARNING", "FAILURE", "OFFLINE"]).optional(),
  })
  .refine((payload) => Object.keys(payload).length > 0, {
    message: "At least one field must be provided",
  });

const LinkCreateSchema = z.object({
  sourceId: z.string().optional(),
  targetId: z.string().optional(),
  sourcePortId: z.string().min(1),
  targetPortId: z.string().min(1),
});

const latestMetrics = new Map<
  string,
  { id: string; trafficLoad: number; rxPower: number; status: "OK" | "WARNING" | "FAILURE" }
>();

let trafficTimer: NodeJS.Timeout | null = null;

const createPortsForDevice = async (deviceId: string, type: DocDeviceType) => {
  const ports: Array<{ deviceId: string; portNumber: number; portType: string; status: string }> = [];

  if (type === "OLT") {
    ports.push({ deviceId, portNumber: 0, portType: "UPLINK", status: "UP" });
    for (let i = 1; i <= 4; i += 1) {
      ports.push({ deviceId, portNumber: i, portType: "PON", status: "UP" });
    }
  } else if (type === "ONU") {
    ports.push({ deviceId, portNumber: 0, portType: "PON", status: "UP" });
    ports.push({ deviceId, portNumber: 1, portType: "LAN", status: "UP" });
  } else if (type === "Splitter") {
    ports.push({ deviceId, portNumber: 0, portType: "IN", status: "UP" });
    for (let i = 1; i <= 8; i += 1) {
      ports.push({ deviceId, portNumber: i, portType: "OUT", status: "UP" });
    }
  } else if (type === "Switch") {
    ports.push({ deviceId, portNumber: 0, portType: "UPLINK", status: "UP" });
    for (let i = 1; i <= 8; i += 1) {
      ports.push({ deviceId, portNumber: i, portType: "ACCESS", status: "UP" });
    }
  }

  if (ports.length > 0) {
    await prisma.port.createMany({ data: ports });
  }
};

const mapDeviceToNode = (device: any) => ({
  id: device.id,
  type: "default",
  position: { x: device.x, y: device.y },
  data: {
    id: device.id,
    name: device.name,
    label: device.name,
    type: toDocDeviceType(device.type) ?? device.type,
    status: device.status,
    ports: device.ports,
  },
});

const mapLinkToEdge = (link: any) => ({
  id: link.id,
  source: link.sourcePort.deviceId,
  target: link.targetPort.deviceId,
  sourceHandle: link.sourcePortId,
  targetHandle: link.targetPortId,
  type: "smoothstep",
  data: {
    fiberLength: link.fiberLength,
    fiberType: link.fiberType,
    status: link.status,
  },
});

const asyncRoute =
  <T extends express.RequestHandler>(handler: T): express.RequestHandler =>
  async (req, res, next) => {
    try {
      await handler(req, res, next);
    } catch (error) {
      next(error);
    }
  };

app.get("/api/health", (_req, res) => {
  res.json({ status: "ok" });
});

app.get(
  "/api/topology",
  asyncRoute(async (_req, res) => {
    const devices = await prisma.device.findMany({ include: { ports: true } });
    const links = await prisma.link.findMany({ include: { sourcePort: true, targetPort: true } });

    res.json({
      nodes: devices.map(mapDeviceToNode),
      edges: links.map(mapLinkToEdge),
    });
  })
);

app.get(
  "/api/devices",
  asyncRoute(async (_req, res) => {
    const devices = await prisma.device.findMany({ include: { ports: true } });
    res.json(devices);
  })
);

app.get(
  "/api/devices/:id",
  asyncRoute(async (req, res) => {
    const device = await prisma.device.findUnique({
      where: { id: req.params.id },
      include: { ports: true },
    });

    if (!device) {
      return res.status(404).json({ error: "Device not found" });
    }

    return res.json(device);
  })
);

app.post(
  "/api/devices",
  asyncRoute(async (req, res) => {
    const payload = DeviceCreateSchema.parse(req.body);

    let network = await prisma.network.findFirst();
    if (!network) {
      network = await prisma.network.create({ data: { name: "Default" } });
    }

    const created = await prisma.device.create({
      data: {
        networkId: network.id,
        name: payload.name,
        type: payload.type,
        model: "Generic",
        x: Math.round(payload.x),
        y: Math.round(payload.y),
        status: "OK",
      },
    });

    await createPortsForDevice(created.id, payload.type);

    const deviceWithPorts = await prisma.device.findUniqueOrThrow({
      where: { id: created.id },
      include: { ports: true },
    });

    io.emit("device:created", deviceWithPorts);
    res.status(201).json(deviceWithPorts);
  })
);

app.patch(
  "/api/devices/:id",
  asyncRoute(async (req, res) => {
    const payload = DevicePatchSchema.parse(req.body);
    const id = req.params.id;

    const exists = await prisma.device.findUnique({ where: { id } });
    if (!exists) {
      return res.status(404).json({ error: "Device not found" });
    }

    const updated = await prisma.device.update({
      where: { id },
      data: {
        ...(payload.name !== undefined ? { name: payload.name } : {}),
        ...(payload.x !== undefined ? { x: Math.round(payload.x) } : {}),
        ...(payload.y !== undefined ? { y: Math.round(payload.y) } : {}),
        ...(payload.status !== undefined ? { status: payload.status } : {}),
      },
      include: { ports: true },
    });

    io.emit("device:updated", updated);
    return res.json(updated);
  })
);

app.delete(
  "/api/devices/:id",
  asyncRoute(async (req, res) => {
    const id = req.params.id;
    const exists = await prisma.device.findUnique({ where: { id } });

    if (!exists) {
      return res.status(404).json({ error: "Device not found" });
    }

    await prisma.link.deleteMany({
      where: {
        OR: [{ sourcePort: { deviceId: id } }, { targetPort: { deviceId: id } }],
      },
    });

    await prisma.port.deleteMany({ where: { deviceId: id } });
    await prisma.device.delete({ where: { id } });

    io.emit("device:deleted", { id });
    return res.status(204).send();
  })
);

app.get(
  "/api/links",
  asyncRoute(async (_req, res) => {
    const links = await prisma.link.findMany({
      include: {
        sourcePort: true,
        targetPort: true,
      },
    });

    res.json(links);
  })
);

app.post(
  "/api/links",
  asyncRoute(async (req, res) => {
    const payload = LinkCreateSchema.parse(req.body);

    if (payload.sourcePortId === payload.targetPortId) {
      return res.status(400).json({ error: "sourcePortId and targetPortId must be different" });
    }

    const [sourcePort, targetPort] = await Promise.all([
      prisma.port.findUnique({ where: { id: payload.sourcePortId } }),
      prisma.port.findUnique({ where: { id: payload.targetPortId } }),
    ]);

    if (!sourcePort || !targetPort) {
      return res.status(404).json({ error: "Source or target port not found" });
    }

    const occupied = await prisma.link.findFirst({
      where: {
        OR: [
          { sourcePortId: payload.sourcePortId },
          { targetPortId: payload.sourcePortId },
          { sourcePortId: payload.targetPortId },
          { targetPortId: payload.targetPortId },
        ],
      },
    });

    if (occupied) {
      return res.status(409).json({ error: "Port already occupied" });
    }

    const link = await prisma.link.create({
      data: {
        sourcePortId: payload.sourcePortId,
        targetPortId: payload.targetPortId,
        fiberLength: 10,
        fiberType: "SMF",
        status: "OK",
      },
      include: {
        sourcePort: true,
        targetPort: true,
      },
    });

    io.emit("link:created", link);
    return res.status(201).json(link);
  })
);

app.delete(
  "/api/links/:id",
  asyncRoute(async (req, res) => {
    const id = req.params.id;
    const exists = await prisma.link.findUnique({ where: { id } });

    if (!exists) {
      return res.status(404).json({ error: "Link not found" });
    }

    await prisma.link.delete({ where: { id } });
    io.emit("link:deleted", { id });
    return res.status(204).send();
  })
);

app.get(
  "/api/ports/summary/:deviceId",
  asyncRoute(async (req, res) => {
    const ports = await prisma.port.findMany({
      where: { deviceId: req.params.deviceId },
      include: {
        outgoingLink: true,
        incomingLink: true,
      },
      orderBy: { portNumber: "asc" },
    });

    res.json(ports);
  })
);

app.get("/api/metrics/snapshot", (_req, res) => {
  res.json(Array.from(latestMetrics.values()));
});

app.use((err: unknown, _req: express.Request, res: express.Response, _next: express.NextFunction) => {
  if (err instanceof z.ZodError) {
    return res.status(400).json({ error: "Validation failed", details: err.issues });
  }

  console.error(err);
  return res.status(500).json({ error: "Internal server error" });
});

const startTrafficLoop = () => {
  if (trafficTimer) {
    return;
  }

  trafficTimer = setInterval(async () => {
    try {
      const devices = await prisma.device.findMany({
        select: { id: true, type: true },
      });

      const updates = devices.map((device) => {
        const normalizedType = toDocDeviceType(device.type) ?? "Switch";
        const rxPowerBase = normalizedType === "ONU" ? -18 : -10;
        const trafficBase = normalizedType === "OLT" ? 65 : 35;

        const trafficLoad = Math.min(100, Math.max(0, Math.round(trafficBase + (Math.random() * 40 - 20))));
        const rxPower = Number((rxPowerBase - Math.random() * 12).toFixed(2));

        const status: "OK" | "WARNING" | "FAILURE" =
          rxPower >= -27 ? "OK" : rxPower > -30 ? "WARNING" : "FAILURE";

        const update = { id: device.id, trafficLoad, rxPower, status };
        latestMetrics.set(device.id, update);
        return update;
      });

      if (updates.length > 0) {
        io.emit("device:metrics", updates);
        updates.forEach(({ id, status }) => {
          io.emit("device:status", { id, status });
        });
      }
    } catch (error) {
      console.error("Simulation error:", error);
    }
  }, TRAFFIC_INTERVAL_MS);
};

export const stopTrafficLoop = () => {
  if (trafficTimer) {
    clearInterval(trafficTimer);
    trafficTimer = null;
  }
};

export const start = async () => {
  if (process.env.NODE_ENV !== "production") {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa",
      root: path.resolve(__dirname, "client"),
      configFile: path.resolve(__dirname, "client/vite.config.ts"),
    });
    app.use(vite.middlewares);
  } else {
    app.use(express.static(path.resolve(__dirname, "client/dist")));
    app.get("*", (_req, res) => {
      res.sendFile(path.resolve(__dirname, "client/dist/index.html"));
    });
  }

  startTrafficLoop();

  httpServer.listen(PORT, "0.0.0.0", () => {
    console.log(`Server running on http://localhost:${PORT}`);
  });
};

if (process.env.NODE_ENV !== "test") {
  start();
}

export { app, io, prisma };
