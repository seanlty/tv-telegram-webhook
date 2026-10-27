# Railway Migration and Credential Rotation

## Deployment

Use GitHub as the source for two services in one Railway project/environment.
Prepare a migration branch before modifying any existing deployment branch.

| Service | Source / command | Variables | Storage / network |
| --- | --- | --- | --- |
| Web | Root Dockerfile; default command | TV_SECRET, REDIS_URL | No volume; HTTPS domain; healthcheck / |
| Worker | Dockerfile.worker; python -m src.main worker | TG_TOKEN, TG_CHAT_ID, REDIS_URL, batch variables | No volume or public domain; one replica |
| Redis | Railway Redis template; generated new password | Template-managed | Persistent /data; private network only |

Use the same region for all three services. Disable sleeping for Web and Worker.
Set the draining period to 30 seconds; Docker commands forward SIGTERM.
Do not configure an HTTP healthcheck on Worker. Keep Worker at one replica:
the Telegram limiter is local to each process, not shared across workers.

On both application services set `REDIS_URL=${{Redis.REDIS_URL}}`. Do not also set
the old `REDIS_CONNECTION_STRING`, which has higher priority in the code.
On Worker retain:

```env
BATCH_SECONDS=2
BATCH_MAX=200
TELEGRAM_MIN_INTERVAL=1.1
DEDUP_TTL_SECONDS=300
QUEUE_KEY=tv:signals
DEDUP_PREFIX=tv:dedup:
```

No Telegram token is needed on Web. No TradingView secret is needed on Worker.
Do not copy Zeabur-generated hostnames, PASSWORD, PORT, or platform metadata.
Let Railway provide the Web port. Docker images include only requirements and src.
The application does not automatically load .env files; export variables in your
shell or set them in Railway.

## Rotation

Never paste credentials into chat, shell command arguments, commits, or logs.
New credentials belong only in Railway and the corresponding caller.

| Credential | Issuer / control panel | Action |
| --- | --- | --- |
| TG_TOKEN | Telegram @BotFather, existing bot, API Token controls | Revoke the old token and generate a replacement; retain the bot and memberships |
| TV_SECRET | This application's shared secret | Generate a new random value; set on Railway Web and all TradingView alerts; retire old endpoint/secret |
| Redis password / URL aliases | Old Redis auth configuration; Railway Redis template | Use a fresh generated password on Railway; revoke/change old authentication and retire old public access after data handling |
| TG_CHAT_ID | Existing Telegram destination | Identifier, not a token; retain unless the destination changes |
| GitHub PAT / deploy key, if found | GitHub Settings > Developer settings / repository Deploy keys | Revoke credentials actually stored on the affected platform; use the Railway GitHub App |
| Zeabur GitHub App access | GitHub Settings > Applications > Installed GitHub Apps | Review audit events; remove this repo's access after migration without disrupting other projects |

The account owner must perform BotFather revocation and enter new credentials.
Revocation stops sends using the old token immediately. Pause alerts during the
cutover window and account for pending signals before revoking it.

To minimize copying, run locally:

```powershell
.\.venv\Scripts\python.exe scripts\prepare_rotation.py
```

Enter the NEW bot token and current chat ID at hidden prompts. The script generates
a random 256-bit webhook secret and writes three private files without printing
credentials or contacting a service:

- `.secrets/railway-web.env`: import with Railway Web Variables > Raw Editor.
- `.secrets/railway-worker.env`: import with Worker Variables > Raw Editor.
- `.secrets/tradingview-alert.json`: TradingView message; adjust side/strategy.

These files are ignored by Git and excluded from Docker builds. They are plaintext
local files, not encrypted backups. Store credentials in your password manager and
remove the temporary files once verified. Seal TG_TOKEN and TV_SECRET in Railway.

Changing a connection-string variable does not revoke the database password.
Inspect the old variable supplying --requirepass and rotate it and its clients
while still running, or retire the old database after cutover and the backup
decision. Do not import old passwords into Railway.

## Data and Cutover

Redis stores unsent signals and short-lived dedup keys. The application does not
write uploads, SQLite databases, or files to data/. An empty queue does not prove
there is no in-flight Worker batch or no data in other Redis databases.

1. Inventory volumes, all Redis databases, config mounts and domains. Keep the
   actual audit local and record credential names/references only.
2. Pause incoming TradingView alerts. Let the old Worker finish; verify the queue
   and any in-flight batch are drained. Recheck at cutover, not just preparation.
3. If Redis contains required data, take a protected backup and restore it in an
   isolated environment before switching. Do not replay stale trading alerts
   blindly. If all databases are empty after draining, fresh Redis suffices for
   live data. Retain any required historical backup securely.
4. Rotate credentials at their issuers; deploy Web/Worker with fresh Redis
   credentials and verify health. Do not put the new secrets back into Zeabur.
5. Test one uniquely marked signal end to end and confirm Telegram delivery.
   Resend it to verify deduplication; check burst handling and queue draining.
   Never log full webhook bodies or Telegram request URLs.
6. Update every TradingView alert's webhook URL AND secret. A *.zeabur.app address
   cannot transfer; use Railway HTTPS. For owned custom domains, change DNS only
   after verifying the replacement service.
7. Suspend old services after verification and backup decisions; revoke old
   credentials even if retaining the deployments. Never roll back to compromised
   keys. Remove Zeabur GitHub App access when no longer required by other projects.

The current queue uses LPOP, not an acknowledged processing queue. SIGKILL,
machine failure, or too-short draining periods can lose an in-flight batch.
Graceful shutdown is not an exactly-once guarantee. Retrying a Telegram request
whose response was lost can also duplicate a delivered message.

## Verification

Use Python 3.11+, a virtual environment, and `pip install -r requirements.txt`.

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_*.py -v
.\.venv\Scripts\python.exe -B tests\smoke_test.py
.\.venv\Scripts\python.exe -B scripts\audit_config.py
```

Security tests need no Redis. Smoke tests use the actual async Redis client, a
random isolated key prefix and fake Telegram delivery. Redis defaults to localhost;
TEST_REDIS_URL can select a dedicated test instance. Audit output reports names
and suspected credential locations only. Pattern scans do not prove no secret
ever existed.

Sources checked 2026-10-27:

- [Migration decision guide](https://raymondhouch.com/lifehacker/digital-workflow/zeabur-migration-guide/)
- [Zeabur incident report](https://zeabur.com/zh-TW/blogs/october-2026-security-incident)
- [Railway variables](https://docs.railway.com/variables)
- [Railway Dockerfiles](https://docs.railway.com/builds/dockerfiles)
- [Telegram bot management](https://core.telegram.org/bots/features#botfather)
