# Deploying Mwenendo Core

This guide puts the whole system on one Linux machine, behind HTTPS, using
`docker-compose.prod.yml`. The reasoning is in
[ADR-0017](adr/0017-deploy-to-a-single-vm-with-compose.md).

**Read this first: nothing here has been run on a real server yet.** The compose
file validates, the settings are tested, and the pieces were run locally, but the
HTTPS certificate, an Arm build and a provider's firewall have not been tried.
Where a step depends on a provider's console, it says to check the provider's own
documentation, because those screens change.

## What you are deploying

| Container | Does | Reachable from outside? |
|---|---|---|
| `caddy` | HTTPS, certificates, forwards to the app | Yes: ports 80 and 443 |
| `app` | gunicorn serving the API, the admin and the docs | No |
| `worker` | Celery worker: expires overdue reservations | No |
| `beat` | Celery scheduler: sends the one-minute sweep | No |
| `db` | PostgreSQL 17, data in a Docker volume | No |
| `redis` | The task queue, with data on disk | No |
| `migrate` | Applies migrations, then exits | No |

## 1. Where to run it

Any Linux server with Docker works. The first candidate is an **Oracle Cloud Always
Free** virtual machine, because it has the most generous free allowance and can be
stopped and started from its console.

- Oracle's own [Always Free resources page](https://docs.oracle.com/iaas/Content/FreeTier/resourceref.htm)
  lists Arm (Ampere A1) compute and two small AMD machines. **Check the amounts
  there when you sign up.** Some articles say the Arm allowance was reduced in 2026,
  and the official page and those articles disagree.
- Oracle can reclaim a free instance that stays idle (the rule is about low CPU use
  over a week). Do not treat it as a place to keep the only copy of anything.
- Arm capacity is sometimes unavailable at sign-up. If you cannot get an instance,
  or the account is refused, a small paid VPS from any provider runs this guide
  unchanged. Prices vary, so compare a few.

**What fits.** The five processes plus the build need roughly 2 GB of memory to be
comfortable. A 1 GB machine is likely too small (my estimate, not tested).

## 2. Create the machine

1. Create an instance running **Ubuntu 24.04**. On Oracle, choose the Arm shape
   `VM.Standard.A1.Flex` with at least 2 cores and 6 GB if the allowance permits.
2. Add your SSH public key when asked. You log in with `ssh ubuntu@<public-ip>`.
3. **Reserve the public IP address** so it does not change when you stop and start
   the machine. On Oracle this is a "reserved public IP" attached to the instance.
   (Without it, a stopped and restarted machine may get a new address, and your
   domain would point at the old one.)
4. **Open ports 80 and 443** in the provider's network rules (on Oracle, the
   security list or network security group for the subnet). Caddy needs both, even
   though visitors use HTTPS, because it proves ownership of the domain over port 80.
5. **Also open them on the machine itself.** Oracle's Ubuntu images ship with
   firewall rules that block these ports even after the console rules allow them.
   Oracle's documentation on this is the source to follow. The usual commands are:

   ```bash
   sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
   sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
   sudo netfilter-persistent save
   ```

## 3. Get a domain name

Caddy can only get a certificate for a name. Either use one you own, or a free
subdomain such as one from [DuckDNS](https://www.duckdns.org) (check their site for
the current sign-up). Point an **A record** at the server's reserved public IP. Wait
until `ping your-name.duckdns.org` shows that address.

## 4. Install Docker

Follow Docker's official instructions for Ubuntu:
<https://docs.docker.com/engine/install/ubuntu/>. Afterwards:

```bash
sudo systemctl enable docker     # start Docker at boot, so everything returns after a restart
sudo usermod -aG docker $USER    # run docker without sudo (log out and in again)
docker compose version           # compose v2 must be present
```

## 5. Get the code and write the secrets

```bash
git clone https://github.com/Bh3ky/mwenendo-core.git
cd mwenendo-core
cp .env.production.example .env.production
nano .env.production
```

Fill in every value in `.env.production`:

- `DOMAIN`: your name, with no `https://`.
- `ALLOWED_HOSTS`: the same name, plus `127.0.0.1` (the container health check needs it).
- `CSRF_TRUSTED_ORIGINS`: `https://` plus your name.
- `SECRET_KEY` and `POSTGRES_PASSWORD`: generate each with
  `python3 -c "import secrets; print(secrets.token_urlsafe(50))"`.
- Leave `DEBUG=False` and `BEHIND_TLS_PROXY=True`.
- `METRICS_TOKEN` is optional (`/metrics` is already hidden by the proxy).

`.env.production` is ignored by git. Keep a copy of it somewhere safe off the
server: if the machine is lost, so are your secrets.

## 6. Start it

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

The first build takes a few minutes. `migrate` should show as exited with code 0, and `app` as healthy. Then:

```bash
curl -s https://your-name.duckdns.org/health/ready/
```

Expect `{"status": "ready", "checks": {"database": "ok", "redis": "ok"}}`. Then
open `https://your-name.duckdns.org/api/docs` in a browser. A padlock means Caddy got
its certificate. If it did not, run `docker compose ... logs caddy`: the usual
causes are the domain not yet pointing at the server, or port 80 blocked.

Create an admin user:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml \
  run --rm app python manage.py createsuperuser
```

Then add your first product, because a new database has none. Log in at
`https://your-name.duckdns.org/admin/`, add a **Product** (a SKU such as `DEMO-1` and
a name), then add an **Inventory** for it. The inventory starts empty and its counters
are read-only in the admin on purpose, so give it stock from the demo page at
`/demo/` ("Add 10 units"), or with `POST /api/products/DEMO-1/inventory/add`. That way
every change goes through the ledger.

To avoid typing the long command, add this line to `~/.bashrc`:
`alias dcp='docker compose --env-file .env.production -f docker-compose.prod.yml'`

## 7. Updating

```bash
git pull
dcp up -d --build
```

Migrations run automatically before the new app starts. There is a short gap while
the app container is replaced. Watch it with `dcp logs -f app`.

## 8. Pausing and restarting

To pause, stop the instance in the provider's console. To resume, start it.

- Containers restart by themselves (`restart: unless-stopped`, and Docker starts at
  boot). Check with `dcp ps`.
- If you did not reserve the IP address, check it still matches your DNS record.
- Redis keeps its data on disk, and PostgreSQL's data is in a volume, so neither is lost.
- **Reservations that became overdue while paused are expired within about a minute
  of starting**, by the periodic sweep (ADR-0012). Nothing needs repairing by hand.
- Confirm with `curl -s https://your-name.duckdns.org/health/ready/`.

## 9. Backups

Backups are your job, and the most important safety net on a machine that can be
reclaimed.

```bash
# Take one
dcp exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > backup-$(date +%F).sql.gz

# Restore one (into an empty database)
gunzip -c backup-2026-11-27.sql.gz | dcp exec -T db sh -c 'psql -U "$POSTGRES_USER" "$POSTGRES_DB"'
```

Copy the file off the server (`scp`), or it dies with the server. To run it daily,
put the first command in a script and call it from `crontab -e`. **Test a restore
once**, on a spare machine or a scratch database: a backup you have never restored
is a hope, not a backup. After a restore, `dcp run --rm app python manage.py reconcile_stock`
checks the ledger still adds up.

## 10. Before you share the address

- [ ] `.env.production` has real secrets and is not in git (`git status` should not list it).
- [ ] Only ports 80 and 443 are open to the world (check the provider's rules; do not open 5432 or 6379).
- [ ] `https://your-name/metrics` returns 404.
- [ ] You have taken and restored a backup.
- [ ] You know this is a demonstration: **the API has no authentication**, so anyone
      can reserve and cancel stock. Do not put real data in it.
- [ ] `/admin/` is public. Use a strong password, and consider restricting it (for
      example in `deploy/Caddyfile`) before you advertise the address.

## What is not verified

- A real certificate being issued, and renewals. Test with Let's Encrypt's staging
  endpoint first if you will redeploy often, because issuing is rate-limited.
- Building and running on an Arm machine. CI builds only for x86.
- The provider's firewall steps, free allowances and idle-reclamation rules, which
  change and which I could only read about, not try.
- How the stack behaves under load on a small machine. The benchmark in
  [BENCHMARKS.md](BENCHMARKS.md) was run on a laptop.
