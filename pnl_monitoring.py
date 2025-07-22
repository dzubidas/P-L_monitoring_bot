import requests
import time
import os
from typing import Optional, List, Dict

# Load .env file if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

class DeribitAPI:
    def __init__(self, client_id: str, client_secret: str, testnet: bool = False):
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = "https://test.deribit.com/api/v2" if testnet else "https://www.deribit.com/api/v2"
        self.access_token = None
        
    def authenticate(self) -> bool:
        """Authenticate with Deribit API"""
        url = f"{self.base_url}/public/auth"
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials",
            "scope": "session:rest"
        }
        
        try:
            response = requests.get(url, params=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if "result" in data:
                self.access_token = data["result"]["access_token"]
                return True
                
        except requests.RequestException:
            pass
            
        return False
    
    def _request(self, endpoint: str, params: Optional[dict] = None) -> Optional[dict]:
        """Make authenticated request"""
        if not self.access_token and not self.authenticate():
            return None
            
        url = f"{self.base_url}/{endpoint}"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        
        try:
            response = requests.get(url, headers=headers, params=params or {}, timeout=30)
            response.raise_for_status()
            return response.json().get("result")
        except requests.RequestException:
            return None
    
    def get_account_email(self, currency: str = "BTC") -> Optional[str]:
        """Get account email"""
        data = self._request("private/get_account_summary", {"currency": currency, "extended": "true"})
        return data.get("email") if data else None
    
    def get_positions(self, currency: str = "BTC") -> List[dict]:
        """Get active positions"""
        data = self._request("private/get_positions", {"currency": currency, "kind": "future"})
        return [pos for pos in (data or []) if pos.get("size", 0) != 0]

class TelegramBot:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    
    def send_message(self, message: str) -> bool:
        """Send message to Telegram"""
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        
        try:
            response = requests.post(self.url, json=payload, timeout=30)
            response.raise_for_status()
            return True
        except requests.RequestException:
            return False

def load_accounts() -> List[Dict[str, str]]:
    """Load account configurations from environment"""
    accounts = []
    testnet = os.getenv("DERIBIT_TESTNET", "false").lower() == "true"
    
    # Find all client IDs
    client_ids = {}
    for key, value in os.environ.items():
        if key.startswith("DERIBIT_CLIENT_ID") and value:
            suffix = "" if key == "DERIBIT_CLIENT_ID" else key.replace("DERIBIT_CLIENT_ID", "")
            client_ids[suffix] = value
    
    # Match with secrets
    for suffix, client_id in client_ids.items():
        secret = os.getenv(f"DERIBIT_CLIENT_SECRET{suffix}")
        if secret:
            accounts.append({
                "client_id": client_id,
                "client_secret": secret,
                "testnet": testnet,
                "suffix": suffix
            })
    
    accounts.sort(key=lambda x: (x["suffix"] != "", x["suffix"]))
    return accounts

def get_all_positions() -> List[dict]:
    """Get positions for all accounts"""
    accounts = load_accounts()
    results = []
    
    for account in accounts:
        api = DeribitAPI(account["client_id"], account["client_secret"], account["testnet"])
        
        if api.authenticate():
            email = api.get_account_email("BTC")
            positions = api.get_positions("BTC")
            
            if email:
                results.append({"email": email, "positions": positions})
    
    results.sort(key=lambda x: x["email"])
    return results

def format_message(results: List[dict]) -> str:
    """Format results into Telegram message"""
    if not results:
        return "No position data available"
    
    lines = []
    
    for result in results:
        lines.append(f'<b>Deribit</b> {result["email"]}')
        
        positions = result.get('positions', [])
        if positions:
            for i, pos in enumerate(positions):
                size_btc = pos.get('size_currency', 0)
                size_usd = pos.get('size', 0)
                direction = pos.get('direction', '')
                
                if direction == "sell":
                    display_btc = -abs(size_btc)
                    display_usd = -abs(size_usd)
                    dir_text = "SHORT"
                else:
                    display_btc = abs(size_btc)
                    display_usd = abs(size_usd)
                    dir_text = "LONG"
                
                instrument = pos.get('instrument_name', 'Unknown')
                liq_price = pos.get('estimated_liquidation_price')
                liquidation = f"{liq_price:.2f}" if liq_price else "-"
                
                # Format USD with dots as thousand separator
                formatted_usd = f"{abs(display_usd):,.0f}".replace(",", ".")
                if display_usd < 0:
                    formatted_usd = f"-{formatted_usd}"
                
                if i > 0:
                    lines.append("")
                
                lines.append(f"Position: {instrument} | {dir_text} | {display_btc:.5f} BTC / ({formatted_usd} USD)")
                lines.append(f"Liquidation: {liquidation}")
        else:
            lines.append("Position: -")
            lines.append("Liquidation: -")
        
        lines.append("")
        lines.append("")
    
    # Clean up trailing empty lines
    while lines and lines[-1] == "":
        lines.pop()
    
    return "\n".join(lines)

def main():
    """Main function"""
    # Get Telegram credentials
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        print("Error: Missing Telegram credentials")
        return
    
    # Get positions and send to Telegram
    bot = TelegramBot(bot_token, chat_id)
    results = get_all_positions()
    
    if results:
        message = format_message(results)
        success = bot.send_message(message)
        print("Success" if success else "Failed")
    else:
        print("No data retrieved")

if __name__ == "__main__":
    main()