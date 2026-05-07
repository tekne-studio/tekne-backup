import os
import datetime
import subprocess
import shutil
import re
from . import utils
from . import s3_client

def create_backup(config, project, project_config):
    """Create a backup for the specified project"""
    if not project_config:
        return None
    
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d--%H-%M")
    backup_filename = f"{project}--{timestamp}"
    temp_dir = config['settings']['temp_dir']
    backup_dir = os.path.join(temp_dir, f"{project}_{timestamp}")
    zip_file = os.path.join(temp_dir, f"{backup_filename}.zip")
    
    # Define has_db_config at the top level so it's available throughout the function
    db_keys = ['db_host', 'db_name', 'db_user', 'db_pass']
    has_db_config = all(key in project_config for key in db_keys)
    
    try:
        utils.log(f"Creating backup for project: {project}")
        
        # Create temporary directory
        os.makedirs(backup_dir, exist_ok=True)
        
        # Backup database if credentials are provided
        if has_db_config:
            try:
                db_host = project_config['db_host']
                db_name = project_config['db_name']
                db_user = project_config['db_user']
                db_pass = project_config['db_pass']
                
                utils.log(f"Backing up database: {db_name}")
                db_file = os.path.join(backup_dir, f"{project}_database.sql")
                
                mysqldump_cmd = [
                    'mysqldump',
                    '-h', db_host,
                    '-u', db_user,
                    f'-p{db_pass}',
                    db_name
                ]
                
                with open(db_file, 'w') as f:
                    result = subprocess.run(mysqldump_cmd, stdout=f, stderr=subprocess.PIPE)
                    if result.returncode != 0:
                        utils.log(f"ERROR: Database backup failed: {result.stderr.decode('utf-8')}")
                        shutil.rmtree(backup_dir)
                        return None
            except Exception as db_error:
                utils.log(f"ERROR: Database backup failed: {str(db_error)}")
                shutil.rmtree(backup_dir)
                return None
        else:
            utils.log("Database credentials not provided, skipping database backup")
        
        # Backup website files
        if 'website_path' not in project_config:
            utils.log("ERROR: No website_path specified in project configuration")
            shutil.rmtree(backup_dir)
            return None
            
        website_path = project_config['website_path']
        utils.log(f"Backing up website files from: {website_path}")
        
        if not os.path.isdir(website_path):
            utils.log(f"ERROR: Website directory not found: {website_path}")
            shutil.rmtree(backup_dir)
            return None
        
        website_files_dir = os.path.join(backup_dir, "website_files")
        os.makedirs(website_files_dir, exist_ok=True)
        
        # Get exclude patterns if any
        exclude_patterns = project_config.get('exclude', [])
        exclude_args = []
        for pattern in exclude_patterns:
            exclude_args.extend(['--exclude', pattern])
        
        # Use rsync if available, otherwise fallback to cp
        if shutil.which('rsync'):
            rsync_cmd = [
                'rsync',
                '-a'
            ]
            # Add exclude patterns if any
            rsync_cmd.extend(exclude_args)
            rsync_cmd.extend([
                f"{website_path}/",
                f"{website_files_dir}/"
            ])
            
            utils.log(f"Running rsync with exclusions: {' '.join(exclude_args)}")
            result = subprocess.run(rsync_cmd, stderr=subprocess.PIPE)
            if result.returncode != 0:
                utils.log(f"ERROR: Failed to copy website files: {result.stderr.decode('utf-8')}")
                shutil.rmtree(backup_dir)
                return None
        else:
            # This is a simplified fallback that doesn't handle exclusions
            try:
                # Simple copy without exclusions when rsync is not available
                utils.log("WARNING: rsync not available, exclusions won't be applied")
                shutil.copytree(website_path, website_files_dir, dirs_exist_ok=True)
            except Exception as e:
                utils.log(f"ERROR: Failed to copy website files: {str(e)}")
                shutil.rmtree(backup_dir)
                return None
        
        # Create zip archive
        utils.log(f"Creating zip archive: {zip_file}")
        backup_dir_basename = os.path.basename(backup_dir)
        zip_cmd = [
            'zip',
            '-r',
            zip_file,
            backup_dir_basename
        ]
        
        # Change to temp directory before running zip
        original_dir = os.getcwd()
        os.chdir(temp_dir)
        
        result = subprocess.run(zip_cmd, stderr=subprocess.PIPE)
        
        # Change back to original directory
        os.chdir(original_dir)
        
        if result.returncode != 0:
            utils.log(f"ERROR: Failed to create zip archive: {result.stderr.decode('utf-8')}")
            shutil.rmtree(backup_dir)
            return None
        
        # Upload to R2
        r2_key = f"{project}/{backup_filename}.zip"
        utils.log(f"Uploading to R2: {r2_key}")
        
        upload_success = s3_client.upload_to_r2_sigv4(config, zip_file, r2_key)
        
        # Clean up temporary directory
        shutil.rmtree(backup_dir)
        
        if upload_success:
            utils.log(f"Backup completed successfully: {r2_key}")
            return zip_file
        else:
            utils.log("ERROR: Upload to R2 failed")
            if os.path.exists(zip_file):
                os.remove(zip_file)
            return None
            
    except Exception as e:
        utils.log(f"ERROR: Backup failed: {str(e)}")
        if os.path.exists(backup_dir):
            shutil.rmtree(backup_dir)
        if os.path.exists(zip_file):
            os.remove(zip_file)
        return None

def cleanup_backups(config, project):
    """Clean up backups older than retention period while respecting minimum backup count"""
    utils.log(f"Cleaning up old backups for project: {project}")
    
    # Check if retention_time (in seconds) is specified, otherwise use retention_days
    if 'retention_time' in config['settings']:
        retention_seconds = config['settings']['retention_time']
        utils.log(f"Using retention period of {retention_seconds} seconds")
        cutoff_date = datetime.datetime.now() - datetime.timedelta(seconds=retention_seconds)
    else:
        retention_days = config['settings']['retention_days']
        utils.log(f"Using retention period of {retention_days} days")
        cutoff_date = datetime.datetime.now() - datetime.timedelta(days=retention_days)
    
    # Get minimum backups to keep (default: 3 if not specified)
    min_backups = config['settings'].get('min_backups', 3)
    utils.log(f"Minimum backups to keep: {min_backups}")
    
    cutoff_timestamp = cutoff_date.timestamp()
    utils.log(f"Cutoff time: {cutoff_date.strftime('%Y-%m-%d--%H-%M')}")
    
    # Get all backups for this project
    backups = s3_client.list_backups_sigv4(config, project)
    relevant_backups = [b for b in backups if b.startswith(f"{project}/")]
    
    if not relevant_backups:
        utils.log(f"No backups found for project '{project}', nothing to clean up")
        return True
    
    # Process all backups with valid dates
    backup_dates = []
    
    for backup in relevant_backups:
        # Extract full date-time pattern from backup filename using regex
        match = re.search(r'(\d{4}-\d{2}-\d{2}--\d{2}-\d{2})', backup)
        if not match:
            utils.log(f"Skipping backup with unrecognized format: {backup}")
            continue
        
        backup_datetime_str = match.group(1)
        
        try:
            # Parse full date AND time
            backup_datetime = datetime.datetime.strptime(backup_datetime_str, "%Y-%m-%d--%H-%M")
            backup_timestamp = backup_datetime.timestamp()
            
            # Add to our list for sorting
            backup_dates.append((backup, backup_datetime, backup_timestamp))
        except Exception as e:
            utils.log(f"WARNING: Failed to parse date from backup name: {backup} - {str(e)}")
            continue
    
    # Sort backups by date (newest first)
    backup_dates.sort(key=lambda x: x[2], reverse=True)
    
    # Log all found backups
    utils.log(f"Found {len(backup_dates)} backup(s) with valid dates")
    for i, (backup, dt, _) in enumerate(backup_dates):
        utils.log(f"  {i+1}. {backup} (created: {dt.strftime('%Y-%m-%d--%H-%M')})")
    
    # Keep the minimum number of backups regardless of age
    backups_to_keep = backup_dates[:min_backups]
    backups_to_check = backup_dates[min_backups:]
    
    utils.log(f"Keeping {len(backups_to_keep)} newest backups to meet minimum requirement")
    
    # For the remaining backups, apply the retention policy
    deleted_count = 0
    skipped_count = len(backups_to_keep)
    
    for backup, backup_datetime, backup_timestamp in backups_to_check:
        utils.log(f"Checking backup: {backup} (created: {backup_datetime.strftime('%Y-%m-%d--%H-%M')})")
        
        # Check if backup is older than retention period
        if backup_timestamp < cutoff_timestamp:
            utils.log(f"Deleting old backup: {backup}")
            if s3_client.delete_from_r2_sigv4(config, backup):
                deleted_count += 1
        else:
            utils.log(f"Keeping recent backup: {backup}")
            skipped_count += 1
    
    utils.log(f"Cleanup completed. Deleted {deleted_count} old backups, kept {skipped_count} backups in total.")
    return True 