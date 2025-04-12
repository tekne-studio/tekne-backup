import datetime
import sys
import shutil

def log(message):
    """Log messages with timestamp"""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")

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