#!/usr/bin/env python3
"""
Hubspot API Client for Contact Management
Handles adding contacts to Hubspot lists with proper error handling
"""

import os
import requests
import time
from typing import Optional, Dict, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class HubspotClient:
    """
    Hubspot API client for contact list management
    """
    
    def __init__(self, access_token: Optional[str] = None, list_id: Optional[str] = None):
        """
        Initialize Hubspot client
        
        Args:
            access_token: Hubspot private app access token (defaults to env var)
            list_id: Target list ID for contacts (defaults to env var)
        """
        self.access_token = access_token or os.getenv('HUBSPOT_ACCESS_TOKEN')
        self.list_id = list_id or os.getenv('HUBSPOT_LIST_ID') or os.getenv('LIST_ID')
        self.base_url = 'https://api.hubapi.com'
        
        if not self.access_token:
            raise ValueError("HUBSPOT_ACCESS_TOKEN environment variable or access_token parameter is required")
        
        if not self.list_id:
            raise ValueError("HUBSPOT_LIST_ID environment variable or list_id parameter is required")
    
    def _make_request(self, method: str, endpoint: str, data: Optional[Dict] = None, 
                     retries: int = 3, backoff_factor: float = 1.0) -> Optional[Dict[str, Any]]:
        """
        Make authenticated request to Hubspot API with retry logic
        
        Args:
            method: HTTP method (GET, POST, PUT, etc.)
            endpoint: API endpoint path
            data: Request body data
            retries: Number of retry attempts
            backoff_factor: Exponential backoff multiplier
            
        Returns:
            API response data or None if failed
        """
        url = f"{self.base_url}{endpoint}"
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }
        
        for attempt in range(retries + 1):
            try:
                if method.upper() == 'GET':
                    response = requests.get(url, headers=headers, timeout=30)
                elif method.upper() == 'POST':
                    response = requests.post(url, headers=headers, json=data, timeout=30)
                elif method.upper() == 'PUT':
                    response = requests.put(url, headers=headers, json=data, timeout=30)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")
                
                # Handle rate limiting
                if response.status_code == 429:
                    retry_after = int(response.headers.get('Retry-After', 60))
                    if attempt < retries:
                        logger.warning(f"Rate limited. Waiting {retry_after} seconds before retry {attempt + 1}/{retries}")
                        time.sleep(retry_after)
                        continue
                    else:
                        logger.error("Rate limited and max retries exceeded")
                        return None
                
                # Handle success
                if response.status_code in [200, 201, 204]:
                    # Some PUT requests return 204 No Content on success
                    try:
                        return response.json() if response.content else {}
                    except:
                        return {}
                
                # Handle client/server errors
                if response.status_code >= 400:
                    logger.error(f"Hubspot API error {response.status_code}: {response.text}")
                    return None
                    
            except requests.exceptions.RequestException as e:
                if attempt < retries:
                    wait_time = backoff_factor * (2 ** attempt)
                    logger.warning(f"Request failed (attempt {attempt + 1}/{retries + 1}): {e}. Retrying in {wait_time} seconds")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Request failed after {retries + 1} attempts: {e}")
                    return None
        
        return None
    
    def create_or_update_contact(self, email: str, additional_properties: Optional[Dict] = None) -> Optional[str]:
        """
        Create or update a contact in Hubspot
        
        Args:
            email: Contact email address
            additional_properties: Additional contact properties
            
        Returns:
            Contact ID if successful, None if failed
        """
        properties = {'email': email}
        if additional_properties:
            properties.update(additional_properties)
        
        data = {'properties': properties}
        
        # Try to create contact
        response = self._make_request('POST', '/crm/v3/objects/contacts', data)
        
        if response and 'id' in response:
            logger.info(f"Created new contact: {email} (ID: {response['id']})")
            return response['id']
        
        # If creation failed, try to find existing contact
        search_data = {
            'filterGroups': [{
                'filters': [{
                    'propertyName': 'email',
                    'operator': 'EQ',
                    'value': email
                }]
            }]
        }
        
        search_response = self._make_request('POST', '/crm/v3/objects/contacts/search', search_data)
        
        if search_response and search_response.get('results'):
            contact_id = search_response['results'][0]['id']
            logger.info(f"Found existing contact: {email} (ID: {contact_id})")
            return contact_id
        
        logger.error(f"Failed to create or find contact: {email}")
        return None
    
    def add_contact_to_list(self, contact_id: str, list_id: Optional[str] = None) -> bool:
        """
        Add a contact to a Hubspot list
        
        Args:
            contact_id: Hubspot contact ID
            list_id: Target list ID (defaults to instance list_id)
            
        Returns:
            True if successful, False if failed
        """
        target_list_id = list_id or self.list_id
        
        # Use the correct format for adding contacts to lists - JSON array of contact IDs
        data = [contact_id]
        
        response = self._make_request('PUT', f'/crm/v3/lists/{target_list_id}/memberships/add', data)
        
        if response is not None:  # Could be empty dict for successful PUT
            logger.info(f"Added contact {contact_id} to list {target_list_id}")
            return True
        else:
            logger.error(f"Failed to add contact {contact_id} to list {target_list_id}")
            return False
    
    def add_email_to_list(self, email: str, additional_properties: Optional[Dict] = None,
                         list_id: Optional[str] = None) -> bool:
        """
        Complete workflow: create/update contact and add to list
        
        Args:
            email: Contact email address
            additional_properties: Additional contact properties
            list_id: Target list ID (defaults to instance list_id)
            
        Returns:
            True if successful, False if failed
        """
        try:
            # Use only basic properties to avoid custom property errors
            properties = additional_properties or {}
            
            # Create or find contact
            contact_id = self.create_or_update_contact(email, properties)
            if not contact_id:
                return False
            
            # Add to list
            success = self.add_contact_to_list(contact_id, list_id)
            return success
            
        except Exception as e:
            logger.error(f"Error adding email {email} to Hubspot: {e}")
            return False
    
    def test_connection(self) -> bool:
        """
        Test the Hubspot API connection
        
        Returns:
            True if connection successful, False if failed
        """
        try:
            response = self._make_request('GET', '/crm/v3/objects/contacts?limit=1')
            return response is not None
        except Exception as e:
            logger.error(f"Hubspot connection test failed: {e}")
            return False

def log_email_to_hubspot(email: str, metadata: Optional[Dict] = None) -> bool:
    """
    Convenience function to add email to Hubspot list
    
    Args:
        email: Contact email address  
        metadata: Additional contact metadata
        
    Returns:
        True if successful, False if failed
    """
    try:
        client = HubspotClient()
        
        # Start with minimal properties - just email and standard fields
        properties = {}
        # Only use properties that exist in all Hubspot accounts by default
        
        success = client.add_email_to_list(email, properties)
        
        if success:
            logger.info(f"Successfully added email {email} to Hubspot list")
        else:
            logger.error(f"Failed to add email {email} to Hubspot list")
            
        return success
        
    except Exception as e:
        logger.error(f"Error in log_email_to_hubspot: {e}")
        return False

if __name__ == "__main__":
    # Test script
    import sys
    
    if len(sys.argv) != 2:
        print("Usage: python hubspot_client.py <test_email>")
        sys.exit(1)
    
    test_email = sys.argv[1]
    
    # Configure logging
    logging.basicConfig(level=logging.INFO)
    
    # Test connection
    try:
        client = HubspotClient()
        print(f"Testing connection...")
        
        if client.test_connection():
            print("✅ Connection successful")
            
            print(f"Testing email addition: {test_email}")
            success = client.add_email_to_list(test_email, {
                'test_source': 'hubspot_client_test',
                'test_timestamp': datetime.now().isoformat()
            })
            
            if success:
                print(f"✅ Successfully added {test_email} to Hubspot list")
            else:
                print(f"❌ Failed to add {test_email} to Hubspot list")
        else:
            print("❌ Connection failed")
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
