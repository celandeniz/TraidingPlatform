# TraidingPlatform Frontend

Next.js App Router frontend for TraidingPlatform. It talks to the existing FastAPI JSON API and WebSocket server.

## Run

```bash
pnpm install
pnpm dev
pnpm build
```

The frontend expects FastAPI at `http://127.0.0.1:8765` by default:

```bash
NEXT_PUBLIC_API_BASE=http://127.0.0.1:8765 pnpm dev
```

Core routes:

- `/live` - positions plus live `/ws` signal, price, scanner, and order events
- `/positions` - `/api/positions` and `/api/orders`
- `/scanner` - `/api/universe` and `/api/scan?mode=&top_n=`
- `/setup` - `/api/profiles`, `/api/profiles/activate`, and `/api/setup/status`

The legacy vanilla FastAPI dashboard remains available from the backend at `/legacy`.
