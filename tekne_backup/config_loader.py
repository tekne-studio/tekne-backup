import os
import sys
import yaml
from . import utils # Use relative import within the package

def load_config(config_file):
    """Load configuration from YAML file"""
    try:
        if not os.path.isfile(config_file):
            utils.log(f"ERROR: Config file not found: {config_file}")
            sys.exit(1)
        
        utils.log(f"Loading configuration from {config_file}")
        with open(config_file, 'r') as file:
            config = yaml.safe_load(file)
        
        # Validate required configuration
        if not config.get('r2') or not config.get('projects'):
            utils.log("ERROR: Missing required configuration sections (r2, projects)")
            sys.exit(1)
            
        required_r2_keys = ['endpoint', 'access_key', 'secret_key', 'bucket']
        for key in required_r2_keys:
            if key not in config['r2']:
                utils.log(f"ERROR: Missing required R2 configuration: {key}")
                sys.exit(1)
        
        # Set default values if not provided
        if 'settings' not in config:
            config['settings'] = {}
        if 'retention_days' not in config['settings']:
            config['settings']['retention_days'] = 90
        if 'temp_dir' not in config['settings']:
            config['settings']['temp_dir'] = "/tmp/website_backups"
            
        return config
    except Exception as e:
        utils.log(f"ERROR: Failed to load configuration: {str(e)}")
        sys.exit(1)

def get_project_config(config, project):
    """Get configuration for a specific project"""
    if project not in config['projects']:
        utils.log(f"ERROR: Project '{project}' not found in configuration")
        return None
    
    return config['projects'][project] 