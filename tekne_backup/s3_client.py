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
import base64


def _resolve_endpoint(s3_config, key=''):
    """Build (host, canonical_path, full_url) honoring addressing_style.

    path-style:    host = endpoint host,           path = /bucket/key
    virtual-style: host = bucket.endpoint host,    path = /key
    """
    endpoint = s3_config['endpoint'].rstrip('/')
    bucket = s3_config['bucket']
    style = s3_config.get('addressing_style', 'path')

    url_parts = urlparse(endpoint)
    endpoint_host = url_parts.netloc
    scheme = url_parts.scheme or 'https'

    if style == 'virtual':
        host = f"{bucket}.{endpoint_host}"
        path = f"/{key}" if key else "/"
        full_url = f"{scheme}://{host}{path}"
    else:
        host = endpoint_host
        path = f"/{bucket}/{key}" if key else f"/{bucket}/"
        full_url = f"{endpoint}{path}"

    return host, path, full_url


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
    # Get configuration values for retries and timeout if available
    if 'storage' in config and 'upload_retries' in config['storage']:
        max_retries = config['storage']['upload_retries']
    
    if 'storage' in config and 'upload_timeout' in config['storage']:
        timeout = config['storage']['upload_timeout']
    
    utils.log(f"Using upload settings: max_retries={max_retries}, timeout={timeout} seconds")
    
    for attempt in range(1, max_retries + 1):
        try:
            if attempt > 1:
                utils.log(f"Retry attempt {attempt}/{max_retries} for uploading {source_file}")
                
            r2_config = config['storage']
            endpoint = r2_config['endpoint']
            access_key = r2_config['access_key']
            secret_key = r2_config['secret_key']
            bucket = r2_config['bucket']
            region = r2_config.get('region', 'auto')

            # Enhanced debug logging for Opalstack troubleshooting
            utils.log(f"Storage Config: endpoint={endpoint}, bucket={bucket}, region={region}, style={r2_config.get('addressing_style', 'path')}")
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
            
            # Resolve host/path/url based on addressing style
            host, path, upload_url = _resolve_endpoint(r2_config, dest_key)
            utils.log(f"Host: {host}")

            # Setup request parameters
            method = 'PUT'
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
                '--retry', str(max_retries),  # Retry on transient errors
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
            curl_cmd.append(upload_url)
            
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
        r2_config = config['storage']
        access_key = r2_config['access_key']
        secret_key = r2_config['secret_key']
        bucket = r2_config['bucket']
        region = r2_config.get('region', 'auto')

        # Debug info about configuration
        utils.log(f"Listing from bucket: {bucket} with project prefix: {project}/")

        # Resolve host/path/url based on addressing style (no key for listing)
        host, path, base_url = _resolve_endpoint(r2_config)

        # Setup request parameters - use the same SigV4 approach that works for uploads
        method = 'GET'
        prefix = f"{project}/"

        # We need to handle query parameters properly for SigV4
        # First, build the URL without query params for proper signing
        query_params = {'list-type': '2', 'prefix': prefix}

        # Canonical query string needs to be ordered by parameter name
        canonical_qs_parts = []
        for key in sorted(query_params.keys()):
            value = query_params[key]
            encoded_key = urllib.parse.quote(key, safe='')
            encoded_value = urllib.parse.quote(value, safe='')
            canonical_qs_parts.append(f"{encoded_key}={encoded_value}")

        canonical_querystring = '&'.join(canonical_qs_parts)

        # Build the URL for curl with encoded params
        url_with_params = f"{base_url}?{canonical_querystring}"
        
        utils.log(f"List request with canonical query string: {url_with_params}")
        
        # Setup headers with required content-sha256 for empty payload
        amzdate = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
        datestamp = datetime.datetime.utcnow().strftime('%Y%m%d')
        
        # Empty payload hash for GET requests
        empty_payload_hash = 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
        
        headers = {
            'Host': host,
            'X-Amz-Date': amzdate,
            'X-Amz-Content-Sha256': empty_payload_hash  # Required by R2
        }
        
        # Generate the signature using our working SigV4 function
        auth_header, _ = sign_request_v4(
            method, host, region, path, canonical_querystring, headers,
            empty_payload_hash, 's3', access_key, secret_key
        )
        
        headers['Authorization'] = auth_header
        
        # Build curl command
        curl_cmd = ['curl', '-v', '-X', method]
        
        # Add headers to curl command
        for key, value in headers.items():
            curl_cmd.extend(['-H', f'{key}: {value}'])
        
        # Add URL with parameters
        curl_cmd.append(url_with_params)
        
        # Log curl command with redacted authorization
        safe_curl_cmd = curl_cmd.copy()
        for i, arg in enumerate(safe_curl_cmd):
            if 'Authorization:' in arg:
                safe_curl_cmd[i] = 'Authorization: [REDACTED]'
        utils.log(f"List CURL command: {' '.join(safe_curl_cmd)}")
        
        # Execute the curl command
        utils.log("Executing list command with proper SigV4...")
        result = subprocess.run(curl_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        stdout = ""
        stderr = ""
        
        if hasattr(result, 'stdout') and result.stdout:
            stdout = result.stdout.decode('utf-8')
        
        if hasattr(result, 'stderr') and result.stderr:
            stderr = result.stderr.decode('utf-8')
        
        utils.log(f"Response code: {result.returncode}")
        
        if result.returncode != 0:
            utils.log(f"List error: {stderr}")
            # Don't fall back to another method - debug what's happening here first
        
        # Parse XML response to extract file keys
        response = stdout
        
        # Debug response
        utils.log(f"Response length: {len(response)} bytes")
        
        # Log first 200 chars of response for debugging
        if response:
            utils.log(f"Response preview: {response[:200]}...")
        
        # Extract keys
        keys = re.findall(r'<Key>([^<]+)</Key>', response)
        utils.log(f"Found {len(keys)} objects in bucket")
        
        # Log first few keys for debugging
        if keys:
            utils.log(f"First few keys: {keys[:3]}")
            return keys
        else:
            # If we still failed, log verbosely but don't try more methods yet
            utils.log("No keys found in response. Full stderr:")
            utils.log(stderr)
            utils.log("Full stdout (truncated to 1000 chars):")
            utils.log(stdout[:1000])
            return []
            
    except Exception as e:
        utils.log(f"ERROR: Failed to list backups: {str(e)}")
        return []

def list_objects_with_prefix(endpoint, bucket, prefix, access_key, secret_key):
    """
    List objects in a bucket with a specific prefix using a simpler approach
    that's more compatible with R2's requirements
    """
    try:
        url_parts = urlparse(endpoint)
        host = url_parts.netloc
        
        # Use AWS CLI style command which is more reliable for listing
        # This completely bypasses our manual SigV4 signing for listing
        aws_cmd = [
            'curl', 
            '-s', 
            '--location',  # Follow redirects if needed
            '-H', f'Host: {host}'
        ]
        
        # Add basic authorization header directly
        auth_string = f"{access_key}:{secret_key}"
        encoded_auth = base64.b64encode(auth_string.encode()).decode()
        aws_cmd.extend(['-H', f'Authorization: Basic {encoded_auth}'])
        
        # Build URL with proper path style addressing
        url = f"{endpoint}/{bucket}?list-type=2&prefix={urllib.parse.quote(prefix)}"
        aws_cmd.append(url)
        
        utils.log(f"Executing simplified list command: curl -s [AUTH REDACTED] {url}")
        
        result = subprocess.run(aws_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        if result.returncode != 0:
            stderr = result.stderr.decode('utf-8')
            utils.log(f"List error: {stderr}")
            
            # Try alternative approach with AWS tool-style syntax
            utils.log("Trying alternative listing approach...")
            return list_objects_alternative(endpoint, bucket, prefix, access_key, secret_key)
        
        response = result.stdout.decode('utf-8')
        utils.log(f"Response length: {len(response)} bytes")
        
        if response:
            utils.log(f"Response preview: {response[:200]}...")
        
        # Extract keys
        keys = re.findall(r'<Key>([^<]+)</Key>', response)
        utils.log(f"Found {len(keys)} objects in bucket")
        
        if keys:
            utils.log(f"First few keys: {keys[:3]}")
        else:
            utils.log("No keys found in response - trying alternative method")
            return list_objects_alternative(endpoint, bucket, prefix, access_key, secret_key)
            
        return keys
    except Exception as e:
        utils.log(f"Error in list_objects_with_prefix: {str(e)}")
        # Fallback to alternative method
        return list_objects_alternative(endpoint, bucket, prefix, access_key, secret_key)

def list_objects_alternative(endpoint, bucket, prefix, access_key, secret_key):
    """
    Alternative method to list objects using more direct S3 compatible syntax
    """
    try:
        # Use more S3-like syntax for better compatibility
        curl_cmd = ['curl', '-s', '-v']
        
        # URL without query params for proper signing
        url = f"{endpoint}/{bucket}"
        
        # Add the query parameters directly to the URL
        url_with_params = f"{url}?list-type=2&prefix={urllib.parse.quote(prefix)}"
        
        # Add date header for better compatibility
        amzdate = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
        date_header = datetime.datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT')
        
        curl_cmd.extend([
            '-H', f'Date: {date_header}',
            '-H', f'X-Amz-Date: {amzdate}',
            '-H', f'Authorization: AWS {access_key}:{secret_key}'
        ])
        
        curl_cmd.append(url_with_params)
        
        utils.log(f"Executing alternative list command with: {' '.join(curl_cmd).replace(secret_key, '[SECRET]')}")
        
        result = subprocess.run(curl_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        response = result.stdout.decode('utf-8')
        utils.log(f"Alternative response length: {len(response)} bytes")
        
        if response:
            utils.log(f"Alternative response preview: {response[:200]}...")
        
        # Extract keys
        keys = re.findall(r'<Key>([^<]+)</Key>', response)
        utils.log(f"Alternative method found {len(keys)} objects in bucket")
        
        if not keys:
            # Last resort - try without any authentication
            utils.log("Trying to list without authentication (if bucket is public)")
            simple_cmd = ['curl', '-s', url_with_params]
            simple_result = subprocess.run(simple_cmd, stdout=subprocess.PIPE)
            simple_response = simple_result.stdout.decode('utf-8')
            keys = re.findall(r'<Key>([^<]+)</Key>', simple_response)
            utils.log(f"Public attempt found {len(keys)} objects")
        
        return keys
        
    except Exception as e:
        utils.log(f"Error in list_objects_alternative: {str(e)}")
        return []

def delete_from_r2_sigv4(config, key):
    """Delete a file from R2 using SigV4"""
    try:
        r2_config = config['storage']
        access_key = r2_config['access_key']
        secret_key = r2_config['secret_key']
        region = r2_config.get('region', 'auto')

        # Resolve host/path/url based on addressing style
        host, path, delete_url = _resolve_endpoint(r2_config, key)

        # Setup request parameters
        method = 'DELETE'
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
        for hkey, value in headers.items():
            curl_cmd.extend(['-H', f'{hkey}: {value}'])

        # Add URL
        curl_cmd.append(delete_url)
        
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
    r2_config = config['storage']

    # Use public domain if available, otherwise derive from endpoint + addressing style
    if 'public_domain' in r2_config:
        return f"https://{r2_config['public_domain']}/{key}"

    _, _, full_url = _resolve_endpoint(r2_config, key)
    return full_url
