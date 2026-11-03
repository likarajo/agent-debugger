.PHONY: demo up down build logs restart

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
