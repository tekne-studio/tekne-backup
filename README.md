# Tekne Backup

Python utility for website backups to Cloudflare R2 storage.

## Features

- Database and file backups
- Cloudflare R2 integration with SigV4 authentication
- Automatic cleanup of old backups
- Email notifications

## Setup

1. Clone repository
2. `python3 -m pip install -r requirements.txt`
3. `cp backup-config-example.yml backup-config.yml`
4. Edit configuration file
5. Make the script executable: `chmod +x backup.py`

If you're getting "Permission denied" errors when trying to run the script, make sure to set the proper permissions:

```bash
chmod +x backup.py
```

You can confirm the script is executable if you see the execute (x) permission when listing the file:

```bash
ls -l backup.py
# Should show something like: -rwxr-xr-x 1 user group 4562 Apr 12 20:45 backup.py
#                              ^^^ Note the 'x' which indicates executable
```

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

# Create backup and clean
./backup.py --create --cleanup --project=mywebsite
```

## Example of crontab configuration:

To schedule automatic backups, you can use crontab on Linux/Unix systems:

```bash
# Open crontab editor
crontab -e
```

Example crontab entries:

```bash
# Weekly backup every Sunday at 3:00 AM
0 3 * * 0 /usr/bin/python3 /path/to/backup.py --create --cleanup --project=myproject

# Daily backup at 2:00 AM
0 2 * * * /usr/bin/python3 /path/to/backup.py --create --project=myproject

# Monthly backup retention report on the 1st of each month
0 9 1 * * /usr/bin/python3 /path/to/backup.py --mail --project=myproject
```

For important backups, you may want to set up email notifications for any errors:

```bash
# Set email for cron job notifications
MAILTO="admin@example.com"

# Weekly backup with output redirected (only errors will be mailed)
0 3 * * 0 /usr/bin/python3 /path/to/backup.py --create --cleanup --project=myproject 2>&1

# Or log everything to a file
0 3 * * 0 /usr/bin/python3 /path/to/backup.py --create --cleanup --project=myproject > /var/log/backups.log 2>&1
```

Adjust the paths and schedules according to your specific needs.

## Configuration

Set up your projects, R2 credentials, and retention policies in `backup-config.yml`.

### Database Configuration

The database backup is optional. For sites using SQLite or static sites that don't require database backups, you can simply omit the database credentials from the project configuration:

```yaml
# Project with MySQL database
mywordpress:
  db_host: "localhost"
  db_name: "database_name"
  db_user: "username"
  db_pass: "password"
  website_path: "/path/to/site"

# Project without database backup (for SQLite or static sites)
mystaticsite:
  website_path: "/path/to/site"
  exclude:
    - "cache/*"
    - "tmp/*"
```

When database credentials are not provided, the backup process will skip the database backup step and only back up the files.

## Project Structure

The project is organized as follows:

```
tekne-backup/
├── backup.py                   # Main script entry point
├── backup-config.yml           # Your active configuration file
├── backup-config-example.yml   # Example configuration template
├── README.md                   # This documentation
└── tekne_backup/               # Core functionality module
    ├── __init__.py             # Package initialization
    ├── backup_manager.py       # Handles backup creation and cleanup
    ├── config_loader.py        # Loads and validates configuration
    ├── notification_manager.py # Handles email notifications
    ├── r2_client.py            # Interacts with Cloudflare R2 storage
    └── utils.py                # Shared utility functions
```

### Component Responsibilities

- **backup.py**: Entry point script that parses command-line arguments and orchestrates the backup process.
- **backup_manager.py**: Handles the creation of backups (database dumps and file backups) and cleanup of old backups based on retention policies.
- **config_loader.py**: Loads and validates the YAML configuration file.
- **notification_manager.py**: Manages email notifications for backup completion and sending backup inventory reports.
- **r2_client.py**: Provides functionality for interacting with Cloudflare R2 storage using SigV4 authentication.
- **utils.py**: Contains utility functions used across the project, such as logging and date handling.

## Requirements

- Python 3.6+
- Database tools (mysqldump/pg_dump)
- Compression tools (tar, gzip)
