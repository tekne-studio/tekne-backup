import os
import datetime
import subprocess
import hmac
import hashlib
import urllib.parse
import re
from urllib.parse import urlparse
from . import utils # Use relative import

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

def upload_to_r2_sigv4(config, source_file, dest_key):
    """Upload a file to R2 using SigV4 authentication"""
    try:
        r2_config = config['r2']
        endpoint = r2_config['endpoint']
        access_key = r2_config['access_key']
        secret_key = r2_config['secret_key']
        bucket = r2_config['bucket']
        
        # Get file size and content hash
        file_size = os.path.getsize(source_file)
        
        # Calculate file hash (SHA256)
        sha256_hash = hashlib.sha256()
        with open(source_file, 'rb') as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        file_hash = sha256_hash.hexdigest()
        
        # Extract host and path from endpoint
        url_parts = urlparse(endpoint)
        host = url_parts.netloc
        
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
        
        # Build curl command
        curl_cmd = ['curl', '-v', '-X', method]
        
        # Add headers to curl command
        for key, value in headers.items():
            curl_cmd.extend(['-H', f'{key}: {value}'])
        
        # Add file to upload
        curl_cmd.extend(['-T', source_file])
        
        # Add URL
        curl_cmd.append(f'{endpoint}{path}')
        
        # Execute the curl command
        utils.log(f"Executing upload command (SigV4)")
        result = subprocess.run(curl_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        if result.returncode == 0:
            utils.log("Upload successful")
            return True
        else:
            stderr = result.stderr.decode('utf-8')
            stdout = result.stdout.decode('utf-8')
            utils.log(f"Upload error: {stderr}")
            utils.log(f"Upload output: {stdout}")
            return False
            
    except Exception as e:
        utils.log(f"ERROR: Failed to upload file: {str(e)}")
        return False

def list_backups_sigv4(config, project):
    """List all backups for a project using SigV4"""
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
        method = 'GET'
        path = f'/{bucket}/'
        prefix = f"{project}/"
        params = f'list-type=2&prefix={urllib.parse.quote(prefix)}'
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
        curl_cmd.append(f'{endpoint}{path}?{params}')
        
        # Execute the curl command
        result = subprocess.run(curl_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        if result.returncode != 0:
            stderr = result.stderr.decode('utf-8')
            utils.log(f"List error: {stderr}")
            return []
        
        # Parse XML response to extract file keys
        response = result.stdout.decode('utf-8')
        
        try:
            # Use regex to extract Keys (more reliable than XML parsing for potentially malformed responses)
            keys = re.findall(r'<Key>([^<]+)</Key>', response)
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