# TraidingPlatform — convenience targets.

VIBE_COMPOSE := docker compose -f deploy/vibe-trading/docker-compose.yml

.PHONY: vibe-up vibe-down vibe-logs vibe-ui

## Start the Vibe-Trading sidecar (detached) on 127.0.0.1:8899
vibe-up:
	$(VIBE_COMPOSE) up -d

## Stop and remove the Vibe-Trading sidecar
vibe-down:
	$(VIBE_COMPOSE) down

## Tail Vibe-Trading sidecar logs
vibe-logs:
	$(VIBE_COMPOSE) logs -f

## Start the sidecar AND Vibe's own React UI on 127.0.0.1:5899
vibe-ui:
	$(VIBE_COMPOSE) --profile frontend up -d
