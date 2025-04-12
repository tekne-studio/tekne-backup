# Tekne Backup

Python utility for website backups to Cloudflare R2 storage.

## Features

- Database and file backups
- Cloudflare R2 integration with SigV4 authentication
- Automatic cleanup of old backups
- Email notifications

## Setup

1. Clone repository
2. `pip install -r requirements.txt`
3. `cp backup-config-example.yml backup-config.yml`
4. Edit configuration file

## Usage

```bash
# Create backup
./backup.py --create --project=mywebsite

# List backups
./backup.py --list --project=mywebsite

# Clean old backups
./backup.py --cleanup --project=mywebsite

# Send report
./backup.py --mail --project=mywebsite
```

## Configuration

Set up your projects, R2 credentials, and retention policies in `backup-config.yml`.

## Requirements

- Python 3.6+
- Database tools (mysqldump/pg_dump)
- Compression tools (tar, gzip)
