# Plusconnect Sync Service

Synchronizace PREVIO rezervací do Loxone (PIN kódy) s více konfigurovatelnými hotely, dashboardem a Postgres úložištěm.

## Rychlý start

1. **Závislosti**
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Konfigurace**
   - Přidejte YAML pro každý hotel do `config/hotels/` (viz `moravskygrunt.yaml`).
   - Nastavte `DATABASE_URL` (Postgres) v prostředí, např. `postgresql://user:pass@host:5432/plusconnect`.

3. **Databáze**
   - Tabulky se vytvoří automaticky při startu.

4. **Spuštění**
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```

5. **Dashboard**
   - Přehled: `/` (potřebuje `key` u detailu hotelu)
   - Detail hotelu: `/hotels/<hotel_id>?key=<read_key>`
   - Změna nastavení: POST stejné URL s Basic Auth (uvedeno v YAML)

6. **Sync**
   - Interval z YAML/DB (výchozí 5 min). Nastavení lze měnit na dashboardu (vyžaduje BasicAuth).

## Klíčové vlastnosti
- PREVIO: `Hotel.searchReservations`, `Hotel.get`, `Get PIN code` (card-locking-keys)
- Loxone: JWT tokeny (`getkey2`, `getjwt`), správa uživatelů (`addoredituser`, `updateuseraccesscode`, `deleteuser`, `getgrouplist`, `checkuserid`)
- Postgres pro stav, logy a sledování vydaných uživatelů
- Per-hotel YAML + runtime úpravy (interval, okna, offsety, TLS verify)
- Dashboard s brandem Plushouse, read-only přes URL key, změny chráněny BasicAuth

## Poznámky k provozu
- Připojení k Loxone přes CloudDNS (`cloud_dns_host`) s volitelným ověřením TLS (`verify_tls`).
- `userid` ve formátu `PLUSCONNECT - <resId>`; idempotentní update.
- Uživatelé se mažou po `delete_after_hours` od konce platnosti.
