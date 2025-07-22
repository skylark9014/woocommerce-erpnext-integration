# WooCommerce–ERPNext Integration Middleware

## Purpose

This project provides a self-contained, Dockerized FastAPI middleware that:

- Receives ERPNext webhooks for Item updates.
- Pushes product updates to WooCommerce via REST API.
- Receives WooCommerce webhooks (e.g. orders) and syncs them to ERPNext.
- Designed to be repeatably deployable on a dedicated DEV server.

---

## Folder Layout

woocommerce-erpnext-integration/
├── app/ # Python source code
├── .env # Your secrets and config (NEVER COMMIT)
├── .env.example # Template for .env
├── Dockerfile # Defines how to build the service
├── docker-compose.yml # Defines how to run the stack
├── init.sh # Automates setup and rebuild
└── README.md # This file

---

## Prerequisites

- Ubuntu 24.04 LTS (or similar)
- Docker Engine + Docker Compose V2
- Traefik already set up as reverse proxy
- Your ERPNext server publicly reachable at:

  - **https://records.techniclad.co.za**

- WooCommerce site reachable at:

  - **https://www.techniclad.co.za**

---

## First-Time Setup

1️⃣ Clone or copy this project folder to your DEV server:

	/home/jannie/woocommerce-erpnext-integration

2️⃣ Create your `.env` file:

	cp .env.example .env
	nano .env

✅ Fill in your:

- ERPNext API URL, key, secret
- WooCommerce REST API credentials
- WooCommerce webhook secret

3️⃣ Build and start:

	./init.sh

✅ The script will:

- Verify .env
- Pull base images
- Build the container
- Start it with docker-compose

---

## How to Recover After Server Wipe

After reverting your DEV server to a clean snapshot:

1️⃣ Restore this folder (from backup or Git):

	/home/jannie/woocommerce-erpnext-integration

2️⃣ Ensure `.env` exists:

	cp .env.example .env # if missing
	nano .env # re-fill secrets

3️⃣ Run:

	./init.sh

✅ That's it!

---

## Useful Commands

- View running containers:

	docker compose ps

- View logs:

	docker compose logs -f

- Rebuild manually:

	docker compose build

- Stop service:

	docker compose down

---

## Traefik Routing

This project is designed to register automatically with your existing Traefik setup via labels in `docker-compose.yml`.

Example rule (adjust as needed):

Host(records.techniclad.co.za) && PathPrefix(/webhook)

✅ Your middleware will then be reachable at:

	https://records.techniclad.co.za/webhook	
---

## Notes

✅ `.env` is **NOT** version-controlled (for security).  
✅ `.env.example` defines required keys.  
✅ `init.sh` ensures repeatable deployment every time.  

---

## TODO

✅ Add actual FastAPI app source in `/app/`.  
✅ Define endpoint routes.  
✅ Implement ERPNext and WooCommerce REST API calls.

---


