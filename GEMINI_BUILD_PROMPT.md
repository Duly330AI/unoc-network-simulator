# GEMINI_BUILD_PROMPT.md

Instruction:
Build the project described in MASTER_SPEC_UNOC_LITE.md exactly.

Requirements:
- fullstack application
- working dev environment
- start with npm install and npm run dev

Stack must be:

Frontend:
React
TypeScript
React Flow
Tailwind CSS
Zustand

Backend:
Node.js
Express.js

Database:
SQLite
Prisma

Project layout:

/unoc-simulator
  /server
  /client

Frontend must use Vite.

Backend must expose REST API:

/api/networks
/api/devices
/api/links

Simulation engine must run in browser at 100ms tick.

Do not add microservices.
Do not add other frameworks.
Keep architecture deterministic and simple.