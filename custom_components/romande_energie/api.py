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
    
    async def login(self):
        """Log in to the Romande Energie API."""
        try:
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
                    _LOGGER.error(f"Login failed with status code {response.status}")
                    return False

                data = await response.json()
                self.access_token = data.get("access")
                self.refresh_token = data.get("refresh")
                # Set expiration time (typically 1 hour from now)
                self.token_expires_at = datetime.now() + timedelta(minutes=55)
                
                _LOGGER.debug("Login successful")
                return True
                
        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as error:
            _LOGGER.error(f"Error during login: {error}")
            return False

    async def refresh_access_token(self):
        """Refresh the access token."""
        if not self.refresh_token:
            _LOGGER.error("No refresh token available")
            return await self.login()
            
        try:
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
                    _LOGGER.error(f"Token refresh failed with status code {response.status}")
                    return await self.login()

                data = await response.json()
                self.access_token = data.get("access")
                self.token_expires_at = datetime.now() + timedelta(minutes=55)
                
                _LOGGER.debug("Token refresh successful")
                return True
                
        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as error:
            _LOGGER.error(f"Error during token refresh: {error}")
            return await self.login()

    async def check_token(self):
        """Check if token is valid and refresh if needed."""
        if not self.access_token:
            return await self.login()
            
        if self.token_expires_at and datetime.now() >= self.token_expires_at:
            return await self.refresh_access_token()
            
        return True

    async def get_session_info(self):
        """Get session information."""
        if not await self.check_token():
            return None
            
        try:
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
                    _LOGGER.error(f"Get session failed with status code {response.status}")
                    return None

                data = await response.json()
                self.session_id = data.get("SessionID")
                return data
                
        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as error:
            _LOGGER.error(f"Error getting session: {error}")
            return None

    async def get_contracts(self):
        """Get contracts for the account."""
        if not self.session_id:
            session_data = await self.get_session_info()
            if not session_data:
                return None
        
        try:
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
                    _LOGGER.error(f"Get contracts failed with status code {response.status}")
                    return None

                data = await response.json()
                # Get the first contract or the active one
                contracts = data.get("contracts", [])
                if contracts:
                    active_contracts = [c for c in contracts if c.get("StatusID") == "ACTIVE"]
                    if active_contracts:
                        self.contract_id = active_contracts[0].get("ContractId")
                    else:
                        self.contract_id = contracts[0].get("ContractId")
                
                return data
                
        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as error:
            _LOGGER.error(f"Error getting contracts: {error}")
            return None

    async def get_electricity_consumption(self, from_date=None, to_date=None):
        """Get electricity consumption data."""
        if not self.contract_id:
            contracts_data = await self.get_contracts()
            if not self.contract_id:
                return None
        
        # Default to current month if dates not specified
        if not from_date or not to_date:
            today = datetime.now()
            from_date = today.replace(day=1).strftime("%Y-%m-%d")
            to_date = today.strftime("%Y-%m-%d")
        
        try:
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
                    _LOGGER.error(f"Get electricity consumption failed with status code {response.status}")
                    return None

                data = await response.json()
                return data
                
        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as error:
            _LOGGER.error(f"Error getting electricity consumption: {error}")
            return None