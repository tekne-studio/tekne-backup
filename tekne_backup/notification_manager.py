import tempfile
import os
import subprocess
import datetime
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
    subject = f"{subject_prefix} {project} - Backup {status}"
    
    # Create email body
    body = [
        f"Website Backup Report for {project}",
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
        for backup in backups:
            # Generate public URL for the backup
            public_url = r2_client.generate_public_url(config, backup)
            body.append(f"- {backup} ({public_url})")
    
    # Create the email message
    message = "\n".join(body)
    
    # Send email using mail command
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
        except Exception as e:
            utils.log(f"WARNING: Failed to send email to {recipient}: {str(e)}")
    
    utils.log(f"Email notification sent to {len(email_config['to'])} recipients") 