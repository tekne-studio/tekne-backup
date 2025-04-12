import tempfile
import os
import subprocess
import datetime
import re
from . import utils
from . import r2_client

def send_email_notification(config, project, status, backup_file):
    """Send email notification about backup status"""
    if 'email' not in config:
        utils.log("WARNING: No email configuration found, skipping notification")
        return
    
    email_config = config['email']
    if 'from' not in email_config or 'to' not in email_config:
        utils.log("WARNING: Incomplete email configuration, skipping notification")
        return
    
    subject_prefix = email_config.get('subject_prefix', '[BACKUP]')
    subject = f"{subject_prefix} {project.upper()} - Backup {status}"
    
    # Create email body
    body = [
        f"Website Backup Report for {project.upper()}",
        "=================================",
        "",
        f"Status: {status}",
        f"Date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ""
    ]
    
    if status == "SUCCESS" and backup_file and os.path.exists(backup_file):
        # Get filename and size
        filename = os.path.basename(backup_file)
        filesize = os.path.getsize(backup_file)
        
        # Convert size to human-readable format
        if filesize >= 1073741824:
            filesize_str = f"{filesize / 1073741824:.2f} GB"
        elif filesize >= 1048576:
            filesize_str = f"{filesize / 1048576:.2f} MB"
        elif filesize >= 1024:
            filesize_str = f"{filesize / 1024:.2f} KB"
        else:
            filesize_str = f"{filesize} bytes"
        
        body.append(f"Latest backup: {filename}")
        body.append(f"Size: {filesize_str}")
        body.append("")
    else:
        body.append("Backup failed. Please check server logs.")
        body.append("")
    
    body.append("Available backups in R2:")
    body.append("")
    
    backups = r2_client.list_backups_sigv4(config, project)
    if not backups:
        body.append("No backups found.")
    else:
        # Filter out any non-matching files
        relevant_backups = [b for b in backups if b.startswith(f"{project}/")]
        
        # Sort backups by date (newest first)
        relevant_backups.sort(key=utils.extract_date, reverse=True)
        
        for backup in relevant_backups:
            # Generate public URL
            public_url = r2_client.generate_public_url(config, backup)
            body.append(f"- {backup} ({public_url})")
    
    # Create the email message
    message = "\n".join(body)
    
    # Send the email
    _send_email(email_config, subject, message)

def send_backup_report(config, project):
    """Send an email report listing all available backups for a project"""
    if 'email' not in config:
        utils.log("WARNING: No email configuration found, skipping notification")
        return False
    
    email_config = config['email']
    if 'from' not in email_config or 'to' not in email_config:
        utils.log("WARNING: Incomplete email configuration, skipping notification")
        return False
    
    subject_prefix = email_config.get('subject_prefix', '[BACKUP]')
    subject = f"{subject_prefix} {project.upper()} - Backup Inventory Report"
    
    # Create email body
    body = [
        f"Website Backup Inventory Report for {project.upper()}",
        "==========================================",
        "",
        f"Date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ""
    ]
    
    # Get list of backups
    backups = r2_client.list_backups_sigv4(config, project)
    
    # Filter out any non-matching files 
    relevant_backups = [b for b in backups if b.startswith(f"{project}/")]
    
    if not relevant_backups:
        body.append(f"No backups found for project '{project.upper()}'.")
    else:
        # Sort backups by date (newest first)
        relevant_backups.sort(key=utils.extract_date, reverse=True)
        
        body.append(f"Found {len(relevant_backups)} backup(s):")
        body.append("")
        
        # Display each backup with date extracted from name
        for backup in relevant_backups:
            # Extract date from backup name
            date_match = re.search(r'(\d{4}-\d{2}-\d{2}--\d{2}-\d{2})', backup)
            date_str = date_match.group(1) if date_match else "Unknown date"
            
            # Generate public URL
            public_url = r2_client.generate_public_url(config, backup)
            
            body.append(f"- {date_str}: {backup}")
            body.append(f"  URL: {public_url}")
            body.append("")
    
    # Create the email message
    message = "\n".join(body)
    
    # Send the email
    result = _send_email(email_config, subject, message)
    
    if result:
        utils.log(f"Backup report email sent to {len(email_config['to'])} recipients")
    
    return result

def _send_email(email_config, subject, message):
    """Internal function to send an email (reused by both email functions)"""
    try:
        # Send email using mail command
        recipients_sent = 0
        
        for recipient in email_config['to']:
            try:
                with tempfile.NamedTemporaryFile(mode='w', delete=False) as temp_email:
                    temp_email.write(message)
                    temp_email_path = temp_email.name
                
                mail_cmd = [
                    'mail',
                    '-s', subject,
                    recipient
                ]
                
                with open(temp_email_path, 'r') as f:
                    result = subprocess.run(mail_cmd, stdin=f, stderr=subprocess.PIPE)
                
                os.unlink(temp_email_path)
                
                if result.returncode != 0:
                    utils.log(f"WARNING: Failed to send email to {recipient}: {result.stderr.decode('utf-8')}")
                else:
                    recipients_sent += 1
            except Exception as e:
                utils.log(f"WARNING: Failed to send email to {recipient}: {str(e)}")
        
        return recipients_sent > 0
        
    except Exception as e:
        utils.log(f"ERROR: Failed to send email: {str(e)}")
        return False 