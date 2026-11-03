.PHONY: demo up down build logs restart test

demo: up

up:
	docker compose up --build

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f

restart:
	docker compose down
	docker compose up --build

test:
	cd api && REDIS_URL=redis://localhost:6379/15 python3 -m pytest tests/ -v
