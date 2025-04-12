import os
import datetime
import subprocess
import shutil
import re
from . import utils
from . import r2_client

def create_backup(config, project, project_config):
    """Create a backup for the specified project"""
    if not project_config:
        return None
    
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d--%H-%M")
    backup_filename = f"{project}--{timestamp}"
    temp_dir = config['settings']['temp_dir']
    backup_dir = os.path.join(temp_dir, f"{project}_{timestamp}")
    zip_file = os.path.join(temp_dir, f"{backup_filename}.zip")
    
    try:
        utils.log(f"Creating backup for project: {project}")
        
        # Create temporary directory
        os.makedirs(backup_dir, exist_ok=True)
        
        # Backup database
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
        
        # Backup website files
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
        
        # Get upload retry and timeout settings from config, with defaults
        r2_config = config.get('r2', {})
        max_retries = r2_config.get('upload_retries', 3)
        timeout = r2_config.get('upload_timeout', 300)
        
        utils.log(f"Upload settings: retries={max_retries}, timeout={timeout}s")
        
        # Use the enhanced upload function with retry and timeout settings
        upload_success = r2_client.upload_to_r2_sigv4(
            config, 
            zip_file, 
            r2_key,
            max_retries=max_retries,
            timeout=timeout
        )
        
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
    """Clean up backups older than retention period"""
    utils.log(f"Cleaning up old backups for project: {project}")
    
    retention_days = config['settings']['retention_days']
    cutoff_date = datetime.datetime.now() - datetime.timedelta(days=retention_days)
    cutoff_timestamp = cutoff_date.timestamp()
    
    backups = r2_client.list_backups_sigv4(config, project)
    deleted_count = 0
    
    for backup in backups:
        # Extract date from backup filename using regex
        match = re.search(r'(\d{4}-\d{2}-\d{2})', backup)
        if not match:
            continue
        
        backup_date_str = match.group(1)
        
        try:
            # Parse date and convert to timestamp
            backup_date = datetime.datetime.strptime(backup_date_str, "%Y-%m-%d")
            backup_timestamp = backup_date.timestamp()
            
            # Check if backup is older than retention period
            if backup_timestamp < cutoff_timestamp:
                utils.log(f"Deleting old backup: {backup}")
                if r2_client.delete_from_r2_sigv4(config, backup):
                    deleted_count += 1
        except Exception as e:
            utils.log(f"WARNING: Failed to parse date from backup name: {backup}")
            continue
    
    utils.log(f"Cleanup completed. Deleted {deleted_count} old backups.")
    return True 