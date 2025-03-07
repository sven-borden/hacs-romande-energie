"""API client for Romande Energie."""
import logging
from datetime import datetime, timedelta
import aiohttp
import async_timeout
import json

from .const import (
    API_LOGIN_URL,
    API_SESSION_URL,
    API_ACCOUNTS_URL,
    API_CONTRACTS_URL,
    DEFAULT_HEADERS,
)

_LOGGER = logging.getLogger(__name__)


class RomandeEnergieApiClient:
    """API client for Romande Energie."""

    def __init__(self, username, password, session):
        """Initialize the API client."""
        self.username = username
        self.password = password
        self.session = session
        self.access_token = None
        self.refresh_token = None
        self.session_id = None
        self.contract_id = None
        self.token_expires_at = None
        _LOGGER.debug("RomandeEnergieApiClient initialized for user: %s", username)
    
    async def login(self):
        """Log in to the Romande Energie API."""
        try:
            _LOGGER.debug("Attempting login for user: %s", self.username)
            payload = {
                "username": self.username,
                "password": self.password,
            }
            
            async with async_timeout.timeout(10):
                response = await self.session.post(
                    API_LOGIN_URL,
                    json=payload,
                    headers=DEFAULT_HEADERS,
                )
                
                if response.status != 200:
                    _LOGGER.error("Login failed with status code %s: %s", 
                                 response.status, await response.text())
                    return False

                data = await response.json()
                self.access_token = data.get("access")
                self.refresh_token = data.get("refresh")
                # Set expiration time (2 hours from now for Romande Energie)
                self.token_expires_at = datetime.now() + timedelta(minutes=115)
                
                _LOGGER.debug("Login successful for user: %s, token expires at: %s", 
                            self.username, self.token_expires_at)
                return True
                
        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as error:
            _LOGGER.error("Error during login for user %s: %s", self.username, error)
            return False

    async def refresh_access_token(self):
        """Refresh the access token."""
        if not self.refresh_token:
            _LOGGER.error("No refresh token available for user: %s", self.username)
            return await self.login()
            
        try:
            _LOGGER.debug("Attempting to refresh token for user: %s", self.username)
            payload = {
                "refresh": self.refresh_token
            }
            
            async with async_timeout.timeout(10):
                response = await self.session.post(
                    f"{API_LOGIN_URL}refresh/",
                    json=payload, 
                    headers=DEFAULT_HEADERS,
                )
                
                if response.status != 200:
                    _LOGGER.error("Token refresh failed with status code %s: %s", 
                                 response.status, await response.text())
                    return await self.login()

                data = await response.json()
                self.access_token = data.get("access")
                self.token_expires_at = datetime.now() + timedelta(minutes=55)
                
                _LOGGER.debug("Token refresh successful for user: %s, new expiry: %s", 
                            self.username, self.token_expires_at)
                return True
                
        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as error:
            _LOGGER.error("Error during token refresh for user %s: %s", self.username, error)
            return await self.login()

    async def check_token(self):
        """Check if token is valid and refresh if needed."""
        if not self.access_token:
            _LOGGER.debug("No access token available, performing login for user: %s", self.username)
            return await self.login()
            
        if self.token_expires_at and datetime.now() >= self.token_expires_at:
            _LOGGER.debug("Token expired for user %s (expires: %s), refreshing", 
                         self.username, self.token_expires_at)
            return await self.refresh_access_token()
        
        _LOGGER.debug("Token valid for user %s (expires: %s)", self.username, self.token_expires_at)    
        return True

    async def get_session_info(self):
        """Get session information."""
        if not await self.check_token():
            return None
            
        try:
            _LOGGER.debug("Retrieving session info for user: %s", self.username)
            headers = {
                **DEFAULT_HEADERS,
                "Authorization": f"Bearer {self.access_token}"
            }
            
            async with async_timeout.timeout(10):
                response = await self.session.get(
                    API_SESSION_URL,
                    headers=headers,
                )
                
                if response.status != 200:
                    _LOGGER.error("Get session failed for user %s with status code %s: %s", 
                                 self.username, response.status, await response.text())
                    return None

                data = await response.json()
                self.session_id = data.get("SessionID")
                _LOGGER.debug("Session info retrieved successfully for user: %s, session ID: %s", 
                            self.username, self.session_id)
                return data
                
        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as error:
            _LOGGER.error("Error getting session for user %s: %s", self.username, error)
            return None

    async def get_contracts(self):
        """Get contracts for the account."""
        if not self.session_id:
            _LOGGER.debug("No session ID available, retrieving session info for user: %s", self.username)
            session_data = await self.get_session_info()
            if not session_data:
                return None
        
        try:
            _LOGGER.debug("Retrieving contracts for user: %s, session ID: %s", 
                         self.username, self.session_id)
            headers = {
                **DEFAULT_HEADERS, 
                "Authorization": f"Bearer {self.access_token}"
            }
            
            url = f"{API_ACCOUNTS_URL}/{self.session_id}/contracts/"
            
            async with async_timeout.timeout(10):
                response = await self.session.get(
                    url,
                    headers=headers,
                )
                
                if response.status != 200:
                    _LOGGER.error("Get contracts failed for user %s with status code %s: %s", 
                                 self.username, response.status, await response.text())
                    return None

                data = await response.json()
                # Get the first contract or the active one
                contracts = data.get("contracts", [])
                _LOGGER.debug("Retrieved %d contracts for user: %s", len(contracts), self.username)
                
                if contracts:
                    active_contracts = [c for c in contracts if c.get("StatusID") == "ACTIVE"]
                    if active_contracts:
                        self.contract_id = active_contracts[0].get("ContractId")
                        _LOGGER.debug("Selected active contract ID: %s for user: %s", 
                                    self.contract_id, self.username)
                    else:
                        self.contract_id = contracts[0].get("ContractId")
                        _LOGGER.debug("No active contracts found, selected contract ID: %s for user: %s", 
                                    self.contract_id, self.username)
                
                return data
                
        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as error:
            _LOGGER.error("Error getting contracts for user %s: %s", self.username, error)
            return None

    async def get_electricity_consumption(self, from_date=None, to_date=None):
        """Get electricity consumption data."""
        if not self.contract_id:
            _LOGGER.debug("No contract ID available, retrieving contracts for user: %s", self.username)
            contracts_data = await self.get_contracts()
            if not self.contract_id:
                _LOGGER.error("No contract ID found for user: %s", self.username)
                return None
        
        # Default to current month if dates not specified
        if not from_date or not to_date:
            today = datetime.now()
            from_date = today.replace(day=1).strftime("%Y-%m-%d")
            to_date = today.strftime("%Y-%m-%d")
        
        try:
            _LOGGER.debug("Retrieving electricity consumption for user: %s, contract ID: %s, period: %s to %s", 
                         self.username, self.contract_id, from_date, to_date)
            headers = {
                **DEFAULT_HEADERS,
                "Authorization": f"Bearer {self.access_token}"
            }
            
            url = f"{API_CONTRACTS_URL}/{self.contract_id}/services/electricity/curves/?from_date={from_date}&to_date={to_date}"
            
            async with async_timeout.timeout(10):
                response = await self.session.get(
                    url,
                    headers=headers,
                )
                
                if response.status != 200:
                    _LOGGER.error("Get electricity consumption failed for user %s with status code %s: %s", 
                                 self.username, response.status, await response.text())
                    return None

                data = await response.json()
                consumption_points = len(data.get("curves", []))
                _LOGGER.debug("Retrieved %d consumption data points for user: %s, contract: %s", 
                            consumption_points, self.username, self.contract_id)
                return data
                
        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as error:
            _LOGGER.error("Error getting electricity consumption for user %s: %s", self.username, error)
            return None