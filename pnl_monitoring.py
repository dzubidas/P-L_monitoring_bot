import requests
import time
import os
from typing import Optional, List, Dict

# For .env file support (optional - install with: pip install python-dotenv)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

class DeribitAPI:
    def __init__(self, client_id: str, client_secret: str, testnet: bool = False):
        """Initialize Deribit API client"""
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = "https://test.deribit.com/api/v2" if testnet else "https://www.deribit.com/api/v2"
        self.access_token = None
        self.refresh_token = None
        self.token_expires_at = None
        
    def authenticate(self) -> bool:
        """Authenticate with Deribit API"""
        url = f"{self.base_url}/public/auth"
        
        auth_methods = [
            ("GET", {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials",
                "scope": "session:rest"
            }),
            ("POST", {
                "jsonrpc": "2.0",
                "method": "public/auth",
                "params": {
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret
                }
            }),
            ("GET", {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials"
            })
        ]
        
        for method, payload in auth_methods:
            try:
                if method == "GET":
                    response = requests.get(url, params=payload)
                else:
                    response = requests.post(url, json=payload, headers={"Content-Type": "application/json"})
                
                response.raise_for_status()
                data = response.json()
                
                if "result" in data:
                    result = data["result"]
                    self.access_token = result["access_token"]
                    self.refresh_token = result["refresh_token"]
                    self.token_expires_at = time.time() + result.get("expires_in", 900) - 60
                    
                    print("Authentication successful")
                    return True
                    
            except requests.RequestException:
                continue
                
        return False
    
    def _is_token_valid(self) -> bool:
        """Check if current token is still valid"""
        return (self.access_token and self.token_expires_at and 
                time.time() < self.token_expires_at)
    
    def _ensure_authenticated(self) -> bool:
        """Ensure we have a valid authentication token"""
        if not self._is_token_valid():
            return self.authenticate()
        return True
    
    def _make_request(self, endpoint: str, params: Optional[dict] = None) -> Optional[dict]:
        """Make authenticated request to Deribit API"""
        if not self._ensure_authenticated():
            return None
            
        url = f"{self.base_url}/{endpoint}"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        
        print(f"Making request to: {url}")
        print(f"With params: {params}")
        
        try:
            response = requests.get(url, headers=headers, params=params or {})
            print(f"Response status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print("Successfully retrieved data!")
                return data.get("result")
                
        except requests.RequestException:
            pass
            
        return None
    
    def get_account_email(self, currency: str = "BTC") -> Optional[str]:
        """Get account email from account summary"""
        account_data = self._make_request("private/get_account_summary", {
            "currency": currency,
            "extended": "true"
        })
        
        if account_data:
            return account_data.get("email", "Unknown")
        return None
    
    def get_positions(self, currency: str = "BTC") -> Optional[List[dict]]:
        """Get active positions for currency"""
        positions_data = self._make_request("private/get_positions", {
            "currency": currency,
            "kind": "future"
        })
        
        if positions_data:
            # Filter out positions with zero size
            return [pos for pos in positions_data if pos.get("size", 0) != 0]
        return []

class TelegramBot:
    def __init__(self, bot_token: str, chat_id: str):
        """Initialize Telegram Bot"""
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
    
    def send_message(self, message: str) -> bool:
        """Send message to Telegram chat"""
        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        
        try:
            response = requests.post(url, json=payload)
            response.raise_for_status()
            return True
        except requests.RequestException as e:
            print(f"Failed to send Telegram message: {e}")
            return False

def load_accounts_config() -> List[Dict[str, str]]:
    """Load all account configurations from environment variables"""
    accounts = []
    testnet = os.getenv("DERIBIT_TESTNET", "false").lower() == "true"
    
    # Find all DERIBIT_CLIENT_ID variables
    client_id_vars = {}
    for key, value in os.environ.items():
        if key.startswith("DERIBIT_CLIENT_ID") and value:
            suffix = "" if key == "DERIBIT_CLIENT_ID" else key.replace("DERIBIT_CLIENT_ID", "")
            client_id_vars[suffix] = value
    
    # Find corresponding secrets
    for suffix, client_id in client_id_vars.items():
        secret_key = f"DERIBIT_CLIENT_SECRET{suffix}"
        client_secret = os.getenv(secret_key)
        
        if client_secret:
            accounts.append({
                "client_id": client_id,
                "client_secret": client_secret,
                "testnet": testnet,
                "suffix": suffix
            })
    
    if not accounts:
        raise ValueError("No valid account configurations found")
    
    # Sort for consistent order
    accounts.sort(key=lambda x: (x["suffix"] != "", x["suffix"]))
    return accounts

def get_all_positions(currency: str = "BTC") -> List[dict]:
    """Get positions for all configured accounts"""
    try:
        accounts = load_accounts_config()
        results = []
        
        for account in accounts:
            api = DeribitAPI(account["client_id"], account["client_secret"], account["testnet"])
            
            if api.authenticate():
                email = api.get_account_email(currency)
                positions = api.get_positions(currency)
                
                if email:
                    results.append({
                        "email": email,
                        "positions": positions or []
                    })
        
        # Sort by email
        results.sort(key=lambda x: x["email"])
        return results
        
    except ValueError as e:
        print(f"Configuration error: {e}")
        return []

def format_position_message(results: List[dict]) -> str:
    """Format position results into Telegram message"""
    if not results:
        return "No position data available"
    
    message_lines = []
    
    for result in results:
        message_lines.append(f'<b>Deribit</b> {result["email"]}')
        
        positions = result.get('positions', [])
        if positions:
            for i, position in enumerate(positions):
                size_btc = position.get('size_currency', 0)
                size_usd = position.get('size', 0)
                direction_field = position.get('direction', '')
                
                # Show negative values for sell positions
                if direction_field == "sell":
                    display_btc = -abs(size_btc)
                    display_usd = -abs(size_usd)
                    direction = "SHORT"
                else:
                    display_btc = abs(size_btc)
                    display_usd = abs(size_usd)
                    direction = "LONG"
                
                instrument = position.get('instrument_name', 'Unknown')
                liquidation_price = position.get('estimated_liquidation_price')
                liquidation = f"{liquidation_price:.2f}" if liquidation_price else "-"
                
                # Format USD with thousand separators using dots
                formatted_usd = f"{abs(display_usd):,.0f}".replace(",", ".")
                if display_usd < 0:
                    formatted_usd = f"-{formatted_usd}"
                
                # Add empty line before position (except first one)
                if i > 0:
                    message_lines.append("")
                
                message_lines.append(f"Position: {instrument} | {direction} | {display_btc:.5f} BTC / ({formatted_usd} USD)")
                message_lines.append(f"Liquidation: {liquidation}")
        else:
            message_lines.append("Position: -")
            message_lines.append("Liquidation: -")
        
        message_lines.append("")  # Empty line after account
        message_lines.append("")  # Extra empty line for separation between accounts
    
    # Remove the last two empty lines
    if message_lines and message_lines[-1] == "":
        message_lines.pop()
    if message_lines and message_lines[-1] == "":
        message_lines.pop()
    
    return "\n".join(message_lines)

def send_positions_to_telegram():
    """Get position data and send to Telegram"""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        print("Error: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in environment variables")
        return False
    
    bot = TelegramBot(bot_token, chat_id)
    results = get_all_positions("BTC")
    
    if not results:
        bot.send_message("Failed to retrieve position data from any accounts")
        return False
    
    message = format_position_message(results)
    
    print("Sending position data to Telegram...")
    success = bot.send_message(message)
    
    if success:
        print("Successfully sent position data to Telegram")
    else:
        print("Failed to send message to Telegram")
    
    return success

def main():
    """Main function"""
    send_positions_to_telegram()

if __name__ == "__main__":
    main()