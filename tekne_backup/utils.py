import datetime
import sys
import shutil
import re

def log(message):
    """Log messages with timestamp"""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")

def extract_date(backup_name):
    """Extract date from backup name or return a default old date if not found
    
    Args:
        backup_name: String containing a backup name with date in format YYYY-MM-DD--HH-MM
        
    Returns:
        The extracted date string or "0000-00-00--00-00" if no date is found
    """
    date_match = re.search(r'(\d{4}-\d{2}-\d{2}--\d{2}-\d{2})', backup_name)
    # Return a default old date if no match is found
    return date_match.group(1) if date_match else "0000-00-00--00-00"

def check_required_commands():
    """Check if required commands are available"""
    required_commands = ['curl', 'openssl', 'zip', 'mysqldump', 'mail']
    # Check for rsync as well, but don't fail if it's missing, as we have a fallback.
    if not shutil.which('rsync'):
        log("WARNING: 'rsync' command not found. Falling back to 'cp'. Exclusions will not be applied.")
        
    missing_commands = []
    
    for cmd in required_commands:
        if not shutil.which(cmd):
            missing_commands.append(cmd)
    
    if missing_commands:
        log(f"ERROR: Required command(s) not found: {', '.join(missing_commands)}")
        sys.exit(1) 