# GroupMe Export Tool

A comprehensive Python tool for exporting and archiving GroupMe group messages to a local SQLite database. This tool provides both one-time historical backfill and continuous live monitoring capabilities.

## Features

- **Historical Backfill**: Downloads all historical messages from a GroupMe group
- **Live Monitoring**: Daemon mode for continuous message synchronization
- **Comprehensive Data**: Captures messages, attachments, likes, reactions, and member information
- **Resume Capability**: Safe to interrupt and resume - tracks progress automatically
- **Reconciliation**: Handles likes/reactions edits and removals
- **Robust Error Handling**: Retry logic with exponential backoff for API reliability
- **Progress Monitoring**: Real-time progress tracking and verification tools

## Database Schema

The tool creates a SQLite database with the following tables:

- `groups` - Group information
- `members` - User profiles and avatars
- `group_members` - Group membership and roles
- `messages` - Message content, timestamps, and metadata
- `likes` - Message likes/hearts
- `reactions` - Emoji reactions (including hearts)
- `attachments` - Images, files, locations, and other attachments
- `ingestion_progress` - Resume checkpoint tracking

## Prerequisites

- Python 3.7+
- GroupMe API access token
- Group ID for the target group

## Installation

1. Clone this repository:
```bash
git clone <your-repo-url>
cd groupme-export
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables:
```bash
# Option 1: Export in your shell
export GROUPME_TOKEN="your_groupme_api_token"
export GROUPME_GROUP_ID="your_group_id"

# Option 2: Create a .env file (copy from .env.example)
cp .env.example .env
# Edit .env with your actual values
```

## Usage

### Basic Usage

**One-time historical sync:**
```bash
python groupme_ingest.py
```

**Test mode (limited pages):**
```bash
python groupme_ingest.py --test
```

**Skip head-sweep (backfill only):**
```bash
python groupme_ingest.py --no-topoff
```

**Head-sweep only (no backfill):**
```bash
python groupme_ingest.py --topoff-only
```

### Daemon Mode

**Continuous monitoring:**
```bash
python groupme_ingest.py --daemon --interval 30
```

**With reconciliation:**
```bash
python groupme_ingest.py --daemon --reconcile-head 6 --verbose
```

### Command Line Options

- `--test`: Test mode - stop after ~3 pages
- `--no-topoff`: Skip head-sweep after backfilling
- `--topoff-only`: Only run head-sweep (no backfill)
- `--verbose`: Print per-iteration progress
- `--daemon`: Stay running and poll for new messages forever
- `--interval N`: Polling interval in seconds for daemon mode (default: 20)
- `--head-pages N`: How many newest pages to scan each cycle (default: 3)
- `--reconcile-head N`: Reconcile newest N pages for likes/reactions (default: 0)

## Monitoring Tools

### Progress Monitor
```bash
python progress.py
```
Displays real-time statistics about messages, reactions, and attachments in the database.

### Coverage Verification
```bash
python verify_coverage.py
```
Verifies data completeness by comparing database contents with API responses.

## Production Deployment

### Systemd Service

The included `groupme-daemon.service` file can be used to run the tool as a system service:

1. Copy the service file:
```bash
sudo cp groupme-daemon.service /etc/systemd/system/
```

2. Create environment file:
```bash
sudo tee /etc/groupme.env << EOF
GROUPME_TOKEN=your_token_here
GROUPME_GROUP_ID=your_group_id_here
EOF
```

3. Enable and start the service:
```bash
sudo systemctl enable groupme-daemon
sudo systemctl start groupme-daemon
```

### Automated Snapshots

The `snapshot.sh` script provides automated database backups:

1. Set up cron job:
```bash
sudo cp crontab-root.template /etc/cron.d/groupme-snapshot
```

2. Configure SMB mount in `/etc/fstab` (see `fstab` example)

## Security Notes

- **Never commit API tokens or group IDs to version control**
- Use environment variables for all sensitive data
- The `.gitignore` file excludes sensitive files and database files
- Consider using a dedicated service account for API access

## API Rate Limits

The tool implements polite rate limiting with:
- 0.25 second minimum sleep between API calls
- Exponential backoff for rate limit errors (420, 429)
- Retry logic for server errors (5xx)
- Connection timeout handling

## Troubleshooting

### Common Issues

1. **Missing environment variables**: Ensure `GROUPME_TOKEN` and `GROUPME_GROUP_ID` are set
2. **API rate limits**: The tool handles this automatically with backoff
3. **Database locked**: Ensure no other processes are accessing the SQLite file
4. **Network issues**: Check internet connectivity and firewall settings

### Logs

- Daemon mode logs to systemd journal: `journalctl -u groupme-daemon -f`
- Snapshot logs: `/var/log/groupme_snapshot.log`

## File Structure

```
groupme-export/
├── groupme_ingest.py      # Main ingestion script
├── groupme_schema.sql      # Database schema
├── progress.py            # Progress monitoring tool
├── verify_coverage.py     # Data verification tool
├── requirements.txt       # Python dependencies
├── groupme-daemon.service # Systemd service file
├── snapshot.sh           # Backup script
├── crontab-root.template # Cron job template
├── fstab                 # Example fstab configuration
└── README.md             # This file
```

## License

This project is provided as-is for personal use. Please respect GroupMe's Terms of Service and API usage policies.

## Contributing

Contributions are welcome! Please ensure:
- No sensitive data is committed
- Code follows Python best practices
- Tests are included for new features
- Documentation is updated
