# GroupMe Exporter

Continuously archives a GroupMe group chat into a local SQLite database, with periodic snapshots to network storage.

## Architecture

Two independent components run on the host:

| Component | Mechanism | Frequency |
|---|---|---|
| Ingestion daemon | systemd | Polls GroupMe API every 30s |
| Snapshot job | root cron | Backs up SQLite every 30 min |

See [docs/architecture.md](docs/architecture.md) for a full breakdown of the runtime flow, file layout, and component behavior.

---

## Prerequisites

- Linux host with systemd
- Python 3.7+
- A GroupMe API token — get one at [dev.groupme.com](https://dev.groupme.com/)
- The numeric ID of the GroupMe group you want to archive (see below)

### Finding your Group ID

Call the GroupMe API with your token to list your groups:

```
GET https://api.groupme.com/v3/groups?token=YOUR_TOKEN
```

The `id` field in each result is the value you need for `GROUPME_GROUP_ID`.

---

## Repository Layout

```
groupme-exporter/
├── src/
│   ├── groupme_ingest.py      # Main ingestion daemon
│   ├── progress.py            # Progress monitoring tool
│   └── verify_coverage.py     # Data completeness verification
├── schema/
│   └── groupme_schema.sql     # SQLite schema
├── scripts/
│   └── snapshot.sh            # Database snapshot script
├── systemd/
│   ├── groupme-daemon.service # systemd service file
│   └── crontab-root.example   # Example cron entry for snapshots
├── docs/
│   ├── architecture.md        # Full architecture reference
│   └── fstab.example          # Example fstab for SMB snapshot storage
├── .env.example               # All configuration variables (copy to /etc/groupme.env)
└── requirements.txt
```

---

## Deployment

### 1. Clone the repo

```bash
git clone https://github.com/svollmin1/groupme_exporter.git
cd groupme_exporter
```

### 2. Configure secrets

```bash
sudo cp .env.example /etc/groupme.env
sudo chmod 600 /etc/groupme.env
sudo chown root:root /etc/groupme.env
sudo nano /etc/groupme.env
```

Fill in `GROUPME_TOKEN`, `GROUPME_GROUP_ID`, and `GROUPME_INSTALL_DIR`. All other values have defaults. See `.env.example` for the full reference.

### 3. Run the install script

```bash
sudo bash scripts/install.sh
```

This will:
- Copy source files flat into `$GROUPME_INSTALL_DIR`
- Create a Python venv and install dependencies
- Generate `/etc/systemd/system/groupme-daemon.service` from the template
- Enable and start the service

### 4. Set up snapshot cron (optional)

Configure `GROUPME_SNAPSHOT_DEST` in `/etc/groupme.env` and mount the destination, then add the cron entry:

```bash
# See systemd/crontab-root.example for the exact line
sudo crontab -e
```

See [docs/fstab.example](docs/fstab.example) for an example SMB mount configuration.

---

## Updating the host

After pushing changes to the repo, pull and re-run the install script:

```bash
git pull
sudo bash scripts/install.sh
```

---

## Usage (manual / one-off)

```bash
# One-time historical sync
python groupme_ingest.py

# Test mode (3 pages only)
python groupme_ingest.py --test

# Head-sweep only (no backfill)
python groupme_ingest.py --topoff-only

# Run as daemon manually
python groupme_ingest.py --daemon --interval 30 --head-pages 6 --reconcile-head 6 --verbose
```

Full CLI options:

| Flag | Default | Description |
|---|---|---|
| `--daemon` | off | Stay running and poll continuously |
| `--interval N` | 20s | Polling interval in daemon mode |
| `--head-pages N` | 3 | Newest pages to scan each cycle |
| `--reconcile-head N` | 0 | Pages to reconcile for likes/reactions |
| `--topoff-only` | off | Skip backfill, only sweep newest pages |
| `--no-topoff` | off | Skip head-sweep after backfill |
| `--test` | off | Stop after ~3 backfill pages |
| `--verbose` | off | Print per-page progress |

---

## Monitoring

```bash
# Daemon status and logs
sudo systemctl status groupme-daemon
sudo journalctl -u groupme-daemon -f

# Snapshot logs
tail -f /var/log/groupme_snapshot.log

# Message count and ingestion progress
python progress.py

# Completeness check against GroupMe API
python verify_coverage.py
```

---

## Database Schema

SQLite database at `$GROUPME_INSTALL_DIR/groupme.sqlite` (WAL mode):

| Table | Contents |
|---|---|
| `groups` | Group metadata |
| `members` | User profiles |
| `group_members` | Membership and roles |
| `messages` | Message content, timestamps, metadata |
| `likes` | Message likes |
| `reactions` | Emoji reactions |
| `attachments` | Images, files, locations |
| `ingestion_progress` | Backfill checkpoint (resume state) |

---

## Security

- Secrets (`GROUPME_TOKEN`, `GROUPME_GROUP_ID`) are stored in `/etc/groupme.env`, never in the repo
- The service runs with `NoNewPrivileges`, `ProtectSystem`, `ProtectHome`, and `PrivateTmp`
- Database files and the venv are excluded from the repo via `.gitignore`

---

## License

MIT — see [LICENSE](LICENSE).
