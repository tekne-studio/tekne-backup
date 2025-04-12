import os
import datetime
import subprocess
import hmac
import hashlib
import urllib.parse
import re
from urllib.parse import urlparse
from . import utils # Use relative import
import shutil
import time

def sign_request_v4(method, host, region, path, params, headers, payload_hash, service, access_key, secret_key):
    """
    Generate AWS SigV4 signature for the request
    """
    # Create a date for headers and the credential string
    t = datetime.datetime.utcnow()
    amzdate = t.strftime('%Y%m%dT%H%M%SZ')
    datestamp = t.strftime('%Y%m%d')  # Date w/o time, used in credential scope
    
    # Create canonical URI--the part of the URI from domain to query string
    canonical_uri = path
    
    # Create the canonical query string
    canonical_querystring = params
    
    # Create the canonical headers and signed headers
    canonical_headers = ''
    signed_headers = ''
    
    for key, value in sorted(headers.items()):
        canonical_headers += key.lower() + ':' + value + '\n'
        signed_headers += key.lower() + ';'
    
    # Remove the trailing semicolon from signed_headers
    if signed_headers:
        signed_headers = signed_headers[:-1]
    
    # Combine elements to create canonical request
    canonical_request = method + '\n' + canonical_uri + '\n' + canonical_querystring + '\n' + canonical_headers + '\n' + signed_headers + '\n' + payload_hash
    
    # Create the string to sign
    algorithm = 'AWS4-HMAC-SHA256'
    credential_scope = datestamp + '/' + region + '/' + service + '/' + 'aws4_request'
    string_to_sign = algorithm + '\n' + amzdate + '\n' + credential_scope + '\n' + hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()
    
    # Calculate the signature
    # Create the signing key
    def sign(key, msg):
        return hmac.new(key, msg.encode('utf-8'), hashlib.sha256).digest()
    
    signing_key = sign(('AWS4' + secret_key).encode('utf-8'), datestamp)
    signing_key = sign(signing_key, region)
    signing_key = sign(signing_key, service)
    signing_key = sign(signing_key, 'aws4_request')
    
    # Sign the string_to_sign using the signing_key
    signature = hmac.new(signing_key, string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()
    
    # Add signing information to the request
    authorization_header = algorithm + ' ' + 'Credential=' + access_key + '/' + credential_scope + ', ' + 'SignedHeaders=' + signed_headers + ', ' + 'Signature=' + signature
    
    # Return signed authorization header and date for request headers
    return authorization_header, amzdate

def upload_to_r2_sigv4(config, source_file, dest_key, max_retries=3, timeout=300):
    """Upload a file to R2 using SigV4 authentication with retry logic and timeout settings
    
    Args:
        config: Configuration dictionary
        source_file: Path to file to upload
        dest_key: Destination key in R2
        max_retries: Maximum number of retry attempts (default: 3)
        timeout: Connection and operation timeout in seconds (default: 5 minutes)
    """
    for attempt in range(1, max_retries + 1):
        try:
            if attempt > 1:
                utils.log(f"Retry attempt {attempt}/{max_retries} for uploading {source_file}")
                
            r2_config = config['r2']
            endpoint = r2_config['endpoint']
            access_key = r2_config['access_key']
            secret_key = r2_config['secret_key']
            bucket = r2_config['bucket']
            
            # Enhanced debug logging for Opalstack troubleshooting
            utils.log(f"R2 Config: endpoint={endpoint}, bucket={bucket}")
            utils.log(f"File to upload: {source_file}")
            
            # Verify file exists and is readable
            if not os.path.exists(source_file):
                utils.log(f"ERROR: Source file does not exist: {source_file}")
                return False
                
            if not os.access(source_file, os.R_OK):
                utils.log(f"ERROR: Source file is not readable: {source_file}")
                return False
            
            # Get file size and content hash
            file_size = os.path.getsize(source_file)
            file_size_mb = file_size / (1024 * 1024)
            utils.log(f"File size: {file_size_mb:.2f} MB ({file_size} bytes)")
            
            # Calculate file hash (SHA256)
            sha256_hash = hashlib.sha256()
            with open(source_file, 'rb') as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            file_hash = sha256_hash.hexdigest()
            
            # Extract host and path from endpoint
            url_parts = urlparse(endpoint)
            host = url_parts.netloc
            utils.log(f"Host: {host}")
            
            # Setup request parameters
            method = 'PUT'
            path = f'/{bucket}/{dest_key}'
            region = 'auto'  # Cloudflare R2 uses 'auto'
            service = 's3'
            
            # Setup headers
            amzdate = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
            datestamp = datetime.datetime.utcnow().strftime('%Y%m%d')
            
            headers = {
                'Host': host,
                'X-Amz-Date': amzdate,
                'X-Amz-Content-Sha256': file_hash,
                'Content-Type': 'application/zip',
                'Content-Length': str(file_size)
            }
            
            # Generate the signature
            auth_header, _ = sign_request_v4(
                method, host, region, path, '', headers, file_hash,
                service, access_key, secret_key
            )
            
            headers['Authorization'] = auth_header
            
            # Build curl command with timeout settings and better error handling
            curl_cmd = [
                'curl', 
                '--verbose',           # More detailed output
                '--max-time', str(timeout),  # Total time limit
                '--connect-timeout', '60',  # Connection timeout
                '--retry', '3',        # Retry on transient errors
                '--retry-delay', '5',  # Wait between retries
                '--fail',              # Return error on HTTP errors
                '-X', method
            ]
            
            # Add headers to curl command
            for key, value in headers.items():
                curl_cmd.extend(['-H', f'{key}: {value}'])
            
            # Add file to upload
            curl_cmd.extend(['-T', source_file])
            
            # Add URL
            curl_cmd.append(f'{endpoint}{path}')
            
            # Log curl command with redacted authorization
            safe_curl_cmd = curl_cmd.copy()
            for i, arg in enumerate(safe_curl_cmd):
                if 'Authorization:' in arg:
                    safe_curl_cmd[i] = 'Authorization: [REDACTED]'
            utils.log(f"CURL command: {' '.join(safe_curl_cmd)}")
            
            # Check if curl is available in PATH
            if not shutil.which('curl'):
                utils.log("ERROR: curl command not found in PATH")
                return False
                
            # Execute the curl command
            utils.log(f"Executing upload command (SigV4) - attempt {attempt}/{max_retries}")
            utils.log(f"Upload will timeout after {timeout} seconds")
            
            # Show progress by using a subprocess with live output for large files
            if file_size > 50 * 1024 * 1024:  # 50MB
                utils.log(f"Large file detected ({file_size_mb:.2f} MB), showing progress")
                result = subprocess.run(curl_cmd, universal_newlines=True, stderr=subprocess.STDOUT)
            else:
                result = subprocess.run(curl_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            if result.returncode == 0:
                utils.log("Upload successful")
                return True
            else:
                if hasattr(result, 'stderr') and result.stderr:
                    stderr = result.stderr.decode('utf-8') if isinstance(result.stderr, bytes) else result.stderr
                else:
                    stderr = "No error output captured"
                
                if hasattr(result, 'stdout') and result.stdout:
                    stdout = result.stdout.decode('utf-8') if isinstance(result.stdout, bytes) else result.stdout
                else:
                    stdout = "No standard output captured"
                
                utils.log(f"Upload failed with return code: {result.returncode}")
                utils.log(f"Upload error (stderr): {stderr}")
                utils.log(f"Upload output (stdout): {stdout}")
                
                # Check for specific network-related errors that warrant a retry
                network_errors = [
                    "Connection timed out",
                    "Operation timed out",
                    "Connection reset",
                    "Network is unreachable",
                    "Could not resolve host",
                    "SSL connection timeout",
                    "transfer closed with outstanding read data remaining"
                ]
                
                is_network_error = any(err in stderr or err in stdout for err in network_errors)
                
                if is_network_error and attempt < max_retries:
                    # Network error that can be retried - will continue the loop
                    utils.log(f"Network error detected, will retry (attempt {attempt}/{max_retries})")
                    # Wait longer between retries
                    time.sleep(10 * attempt)  # Increasing backoff
                    continue
                else:
                    # Additional diagnostics for common issues
                    if "Could not resolve host" in stderr:
                        utils.log("ERROR: DNS resolution failed. Check network connectivity and endpoint URL.")
                    elif "Connection refused" in stderr:
                        utils.log("ERROR: Connection refused. Check firewall settings and endpoint accessibility.")
                    elif "401" in stderr:
                        utils.log("ERROR: Authentication failed. Check your access_key and secret_key.")
                    elif "403" in stderr:
                        utils.log("ERROR: Permission denied. Check bucket permissions and keys.")
                    elif "413" in stderr:
                        utils.log("ERROR: Upload too large. The file exceeds allowed size limits.")
                    
                    if attempt < max_retries:
                        # Retry again, but with exponential backoff
                        backoff_time = 2 ** attempt * 5  # Exponential backoff
                        utils.log(f"Backing off for {backoff_time} seconds before next retry...")
                        time.sleep(backoff_time)
                    else:
                        utils.log(f"Failed after {max_retries} attempts, giving up")
                        return False
                
        except Exception as e:
            utils.log(f"ERROR: Failed to upload file (attempt {attempt}/{max_retries}): {str(e)}")
            if attempt < max_retries:
                utils.log(f"Will retry in 10 seconds...")
                time.sleep(10)
            else:
                utils.log(f"Maximum retry attempts ({max_retries}) reached")
                return False
    
    # If we got here, all retries failed
    return False

def list_backups_sigv4(config, project):
    """List all backups for a project using SigV4"""
    try:
        r2_config = config['r2']
        endpoint = r2_config['endpoint']
        access_key = r2_config['access_key']
        secret_key = r2_config['secret_key']
        bucket = r2_config['bucket']
        
        # Debug info about configuration
        utils.log(f"Listing from bucket: {bucket} with project prefix: {project}/")
        
        # Extract host and path from endpoint
        url_parts = urlparse(endpoint)
        host = url_parts.netloc
        
        # Setup request parameters
        method = 'GET'
        path = f'/{bucket}/'
        prefix = f"{project}/"
        params = f'list-type=2&prefix={urllib.parse.quote(prefix)}'
        region = 'auto'
        service = 's3'
        
        # Debug info about request
        utils.log(f"List request: {endpoint}{path}?{params}")
        
        # Setup headers
        amzdate = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
        
        headers = {
            'Host': host,
            'X-Amz-Date': amzdate,
            'X-Amz-Content-Sha256': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'  # Empty payload hash
        }
        
        # Generate the signature
        auth_header, _ = sign_request_v4(
            method, host, region, path, params, headers, 
            'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
            service, access_key, secret_key
        )
        
        headers['Authorization'] = auth_header
        
        # Build curl command
        curl_cmd = ['curl', '-s', '-X', method]
        
        # Add headers to curl command
        for key, value in headers.items():
            curl_cmd.extend(['-H', f'{key}: {value}'])
        
        # Add URL with parameters
        full_url = f'{endpoint}{path}?{params}'
        curl_cmd.append(full_url)
        
        # Log curl command with redacted authorization for debugging
        safe_curl_cmd = curl_cmd.copy()
        for i, arg in enumerate(safe_curl_cmd):
            if 'Authorization:' in arg:
                safe_curl_cmd[i] = 'Authorization: [REDACTED]'
        utils.log(f"List CURL command: {' '.join(safe_curl_cmd)}")
        
        # Execute the curl command
        utils.log("Executing list command...")
        result = subprocess.run(curl_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        if result.returncode != 0:
            stderr = result.stderr.decode('utf-8')
            utils.log(f"List error: {stderr}")
            return []
        
        # Parse XML response to extract file keys
        response = result.stdout.decode('utf-8')
        
        # Debug response
        utils.log(f"Response length: {len(response)} bytes")
        
        # Log first 200 chars of response for debugging (truncated to avoid huge logs)
        if response:
            utils.log(f"Response preview: {response[:200]}...")
        else:
            utils.log("Empty response received")
        
        try:
            # Use regex to extract Keys (more reliable than XML parsing for potentially malformed responses)
            keys = re.findall(r'<Key>([^<]+)</Key>', response)
            
            utils.log(f"Found {len(keys)} objects in bucket")
            
            # Log first few keys for debugging
            if keys:
                utils.log(f"First few keys: {keys[:3]}")
            else:
                utils.log("No keys found in response")
                
            return keys
        except Exception as e:
            utils.log(f"WARNING: Failed to parse backup list: {str(e)}")
            # Fallback to empty list if parsing fails
            return []
            
    except Exception as e:
        utils.log(f"ERROR: Failed to list backups: {str(e)}")
        return []

def delete_from_r2_sigv4(config, key):
    """Delete a file from R2 using SigV4"""
    try:
        r2_config = config['r2']
        endpoint = r2_config['endpoint']
        access_key = r2_config['access_key']
        secret_key = r2_config['secret_key']
        bucket = r2_config['bucket']
        
        # Extract host and path from endpoint
        url_parts = urlparse(endpoint)
        host = url_parts.netloc
        
        # Setup request parameters
        method = 'DELETE'
        path = f'/{bucket}/{key}'
        region = 'auto'
        service = 's3'
        
        # Setup headers
        amzdate = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
        
        headers = {
            'Host': host,
            'X-Amz-Date': amzdate,
            'X-Amz-Content-Sha256': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'  # Empty payload hash
        }
        
        # Generate the signature
        auth_header, _ = sign_request_v4(
            method, host, region, path, '', headers, 
            'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
            service, access_key, secret_key
        )
        
        headers['Authorization'] = auth_header
        
        # Build curl command
        curl_cmd = ['curl', '-s', '-X', method]
        
        # Add headers to curl command
        for key, value in headers.items():
            curl_cmd.extend(['-H', f'{key}: {value}'])
        
        # Add URL
        curl_cmd.append(f'{endpoint}{path}')
        
        # Execute the curl command
        result = subprocess.run(curl_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        if result.returncode == 0:
            return True
        else:
            stderr = result.stderr.decode('utf-8')
            utils.log(f"Delete error: {stderr}")
            return False
            
    except Exception as e:
        utils.log(f"ERROR: Failed to delete file: {str(e)}")
        return False

def generate_public_url(config, key):
    """Generate a public URL for a backup file"""
    r2_config = config['r2']
    
    # Use public domain if available, otherwise use endpoint
    if 'public_domain' in r2_config:
        return f"https://{r2_config['public_domain']}/{key}"
    else:
        bucket = r2_config['bucket']
        endpoint = r2_config['endpoint']
        url_parts = urlparse(endpoint)
        host = url_parts.netloc
        
        return f"https://{host}/{bucket}/{key}" 