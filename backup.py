#!/usr/bin/env python3
"""
backup.py - Script to backup websites (WordPress/Craft CMS) to Cloudflare R2
Features:
- Database backup
- File backup
- Cloudflare R2 upload with SigV4 authentication
- Retention management
- Email notifications
- Support for exclusion patterns
Usage: ./backup.py --create --cleanup --project=projectname
"""

import os
import sys
import argparse
import shutil

# Import from tekne-backup library
from tekne_backup import utils
from tekne_backup import config_loader
from tekne_backup import backup_manager
from tekne_backup import r2_client
from tekne_backup import notification_manager

# Default configuration file path
DEFAULT_CONFIG_FILE = "backup-config.yml"

def main():
    """Main function"""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Backup script for websites')
    parser.add_argument('--create', action='store_true', help='Create a new backup')
    parser.add_argument('--cleanup', action='store_true', help='Remove old backups')
    parser.add_argument('--project', required=True, help='Project name')
    parser.add_argument('--config', default=DEFAULT_CONFIG_FILE, help='Path to config file')
    
    args = parser.parse_args()
    
    # Check if at least one operation is specified
    if not args.create and not args.cleanup:
        utils.log("ERROR: No operation specified (--create or --cleanup)")
        parser.print_help()
        sys.exit(1)
    
    # Check required commands
    utils.check_required_commands()
    
    # Load configuration
    config = config_loader.load_config(args.config)
    
    # Create temp directory if needed
    temp_dir = config['settings']['temp_dir']
    os.makedirs(temp_dir, exist_ok=True)
    
    # Execute operations
    success = True
    backup_file = None
    
    try:
        if args.create:
            # Get project configuration
            project_config = config_loader.get_project_config(config, args.project)
            if not project_config:
                sys.exit(1)
                
            # Create backup
            backup_file = backup_manager.create_backup(config, args.project, project_config)
            if not backup_file:
                success = False
        
        if args.cleanup:
            if not backup_manager.cleanup_backups(config, args.project):
                success = False
        
        # Send email notification
        if args.create:
            status = "SUCCESS" if success else "FAILED"
            notification_manager.send_email_notification(config, args.project, status, backup_file)
        
        # Clean up temporary files
        if os.path.exists(temp_dir):
            for filename in os.listdir(temp_dir):
                file_path = os.path.join(temp_dir, filename)
                try:
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.unlink(file_path)
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                except Exception as e:
                    utils.log(f"WARNING: Failed to delete {file_path}: {e}")
        
        if success:
            utils.log("All operations completed successfully")
            sys.exit(0)
        else:
            utils.log("One or more operations failed")
            sys.exit(1)
    except Exception as e:
        utils.log(f"ERROR: Script failed with exception: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()