import requests
import time
import os
from typing import Optional, List, Dict

# For .env file support (optional - install with: pip install python-dotenv)
try:
    from dotenv import load_dotenv
    load_dotenv()  # Load .env file if it exists
except ImportError:
    pass  # python-dotenv not installed, use system environment variables

class DeribitEquityMonitor:
    def __init__(self, client_id: str, client_secret: str, testnet: bool = False):
        """
        Initialize Deribit Equity Monitor
        
        Args:
            client_id: Your Deribit Client ID
            client_secret: Your Deribit Client Secret
            testnet: Use testnet (True) or mainnet (False)
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = "https://test.deribit.com/api/v2" if testnet else "https://www.deribit.com/api/v2"
        self.access_token = None
        self.refresh_token = None
        self.token_expires_at = None
        
    def authenticate(self) -> bool:
        """
        Authenticate with Deribit API and get access/refresh tokens
        
        Returns:
            bool: True if authentication successful, False otherwise
        """
        url = f"{self.base_url}/public/auth"
        
        # Try different authentication methods
        methods_to_try = [
            {
                "method": "GET",
                "params": {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "client_credentials",
                    "scope": "session:rest"
                }
            },
            {
                "method": "POST",
                "json": {
                    "jsonrpc": "2.0",
                    "method": "public/auth",
                    "params": {
                        "grant_type": "client_credentials",
                        "client_id": self.client_id,
                        "client_secret": self.client_secret
                    }
                }
            },
            {
                "method": "GET",
                "params": {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "client_credentials"
                }
            }
        ]
        
        for i, method_config in enumerate(methods_to_try):
            try:
                if method_config["method"] == "GET":
                    response = requests.get(url, params=method_config["params"])
                else:  # POST
                    headers = {"Content-Type": "application/json"}
                    response = requests.post(url, json=method_config["json"], headers=headers)
                
                response.raise_for_status()
                data = response.json()
                
                if "result" in data:
                    result = data["result"]
                    self.access_token = result["access_token"]
                    self.refresh_token = result["refresh_token"]
                    
                    # Calculate token expiry time (refresh 1 minute early)
                    expires_in = result.get("expires_in", 900)
                    self.token_expires_at = time.time() + expires_in - 60
                    
                    print(f"Authentication successful")
                    return True
                    
            except requests.RequestException:
                continue
                
        return False
    
    def is_token_valid(self) -> bool:
        """Check if current token is still valid"""
        return (self.access_token is not None and 
                self.token_expires_at is not None and 
                time.time() < self.token_expires_at)
    
    def refresh_access_token(self) -> bool:
        """
        Refresh the access token using refresh token
        
        Returns:
            bool: True if refresh successful, False otherwise
        """
        if not self.refresh_token:
            return self.authenticate()
            
        url = f"{self.base_url}/public/auth"
        params = {
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token"
        }
        
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            if "result" in data:
                result = data["result"]
                self.access_token = result["access_token"]
                self.refresh_token = result["refresh_token"]
                
                expires_in = result.get("expires_in", 900)
                self.token_expires_at = time.time() + expires_in - 60
                
                return True
            else:
                return self.authenticate()
                
        except requests.RequestException:
            return self.authenticate()
    
    def ensure_authenticated(self) -> bool:
        """Ensure we have a valid authentication token"""
        if not self.is_token_valid():
            if self.refresh_token:
                return self.refresh_access_token()
            else:
                return self.authenticate()
        return True
    
    def make_authenticated_request(self, endpoint: str, params: Optional[dict] = None) -> Optional[dict]:
        """
        Make an authenticated request to Deribit API
        
        Args:
            endpoint: API endpoint (e.g., "private/get_account_summary")
            params: Optional parameters
            
        Returns:
            dict: API response data or None if error
        """
        if not self.ensure_authenticated():
            return None
            
        url = f"{self.base_url}/{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        
        print(f"Making request to: {url}")
        print(f"With params: {params}")
        
        try:
            response = requests.get(url, headers=headers, params=params or {})
            print(f"Response status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"Successfully retrieved data!")
                return data.get("result", data)
            else:
                error_data = response.json() if response.text else {}
                
                # If token is invalid, try to refresh
                if (error_data.get("error", {}).get("code") == 13009 and 
                    error_data.get("error", {}).get("data", {}).get("reason") == "invalid_token"):
                    if self.refresh_access_token():
                        # Retry with new token
                        headers["Authorization"] = f"Bearer {self.access_token}"
                        response = requests.get(url, headers=headers, params=params or {})
                        if response.status_code == 200:
                            data = response.json()
                            return data.get("result", data)
                
                return None
                
        except Exception:
            return None
    
    def get_equity_simple(self, currency: str = "BTC") -> Optional[dict]:
        """
        Get current equity value, username, and email
        
        Args:
            currency: Currency code (BTC, ETH, etc.)
            
        Returns:
            dict: Dictionary with equity, username, and email or None if error
        """
        try:
            account_data = self.make_authenticated_request("private/get_account_summary", {
                "currency": currency,
                "extended": "true"
            })
            
            if account_data and "equity" in account_data:
                equity = account_data["equity"]
                username = account_data.get("username", "Unknown")
                email = account_data.get("email", "Unknown")
                
                return {
                    "username": username,
                    "email": email,
                    "equity": equity,
                    "currency": currency
                }
            else:
                return None
        except Exception:
            return None

class TelegramBot:
    def __init__(self, bot_token: str, chat_id: str):
        """
        Initialize Telegram Bot
        
        Args:
            bot_token: Your Telegram Bot Token
            chat_id: Chat ID where to send messages
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
    
    def send_message(self, message: str) -> bool:
        """
        Send message to Telegram chat
        
        Args:
            message: Message text to send
            
        Returns:
            bool: True if successful, False otherwise
        """
        url = f"{self.base_url}/sendMessage"
        
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML"  # Support for basic formatting
        }
        
        try:
            response = requests.post(url, json=payload)
            response.raise_for_status()
            return True
            
        except requests.RequestException as e:
            print(f"Failed to send Telegram message: {e}")
            return False

def load_accounts_config() -> List[Dict[str, str]]:
    """Load all account configurations from environment variables dynamically"""
    
    accounts = []
    testnet = os.getenv("DERIBIT_TESTNET", "false").lower() == "true"
    
    # Get all environment variables
    env_vars = os.environ
    
    # Find all DERIBIT_CLIENT_ID variables
    client_id_vars = {}
    for key, value in env_vars.items():
        if key.startswith("DERIBIT_CLIENT_ID") and value:
            # Extract the suffix (empty for base, _2, _3, etc.)
            if key == "DERIBIT_CLIENT_ID":
                suffix = ""
            else:
                suffix = key.replace("DERIBIT_CLIENT_ID", "")
            client_id_vars[suffix] = value
    
    # For each client_id, try to find corresponding client_secret
    for suffix, client_id in client_id_vars.items():
        secret_key = f"DERIBIT_CLIENT_SECRET{suffix}"
        client_secret = os.getenv(secret_key)
        
        if client_secret:
            account_name = f"Account {len(accounts) + 1}" if suffix else "Account 1"
            accounts.append({
                "client_id": client_id,
                "client_secret": client_secret,
                "testnet": testnet,
                "name": account_name,
                "suffix": suffix
            })
    
    if not accounts:
        raise ValueError("No valid account configurations found")
    
    # Sort accounts to ensure consistent order (base account first, then numbered)
    accounts.sort(key=lambda x: (x["suffix"] != "", x["suffix"]))
    
    return accounts

def get_all_accounts_equity(currency: str = "BTC") -> List[Optional[dict]]:
    """Get equity for all configured accounts"""
    
    try:
        accounts = load_accounts_config()
        results = []
        
        # Get data for all accounts first
        for account in accounts:
            monitor = DeribitEquityMonitor(
                account["client_id"], 
                account["client_secret"], 
                testnet=account["testnet"]
            )
            
            if monitor.authenticate():
                result = monitor.get_equity_simple(currency)
                if result:
                    results.append(result)
                else:
                    results.append(None)
            else:
                results.append(None)
        
        # Filter out None results and sort by email
        valid_results = [r for r in results if r is not None]
        valid_results.sort(key=lambda x: x['email'])
        
        return valid_results
        
    except ValueError as e:
        print(f"Configuration error: {e}")
        return []

def format_equity_message(results: List[dict]) -> str:
    """Format equity results into Telegram message"""
    
    if not results:
        return "No equity data available"
    
    message_lines = []
    
    for result in results:
        message_lines.append(f"DB {result['email']}")
        message_lines.append(f"Equity: {result['equity']:.8f} {result['currency']}")
        message_lines.append("")  # Empty line between accounts
    
    # Remove the last empty line
    if message_lines and message_lines[-1] == "":
        message_lines.pop()
    
    return "\n".join(message_lines)

def send_equity_to_telegram():
    """Get equity data and send to Telegram"""
    
    # Load Telegram configuration
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        print("Error: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in environment variables")
        return False
    
    # Initialize Telegram bot
    bot = TelegramBot(bot_token, chat_id)
    
    # Get equity data
    results = get_all_accounts_equity("BTC")
    
    if not results:
        bot.send_message("Failed to retrieve equity data from any accounts")
        return False
    
    # Format and send message
    message = format_equity_message(results)
    
    print("Sending equity data to Telegram...")
    success = bot.send_message(message)
    
    if success:
        print("Successfully sent equity data to Telegram")
    else:
        print("Failed to send message to Telegram")
    
    return success

def main():
    """Main function"""
    send_equity_to_telegram()

if __name__ == "__main__":
    main()
