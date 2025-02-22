import logging
import aiohttp
from solana.publickey import PublicKey
from typing import Dict, Optional

logger = logging.getLogger(__name__)

DEXSCREENER_API = "https://api.dexscreener.com/latest/dex/tokens"
BIRDEYE_API = "https://public-api.birdeye.so/public/price"
JUPITER_API = "https://quote-api.jup.ag/v6"
SOL_MINT = "So11111111111111111111111111111111111111112"
BIRDEYE_API_KEY = "56e1ffe020b341ed98a4902f8dfd58e9"  # Your provided key

async def get_solana_token_info(token_address: str) -> Optional[Dict]:
    """
    Fetch token info (name, symbol, price, liquidity, market cap) for a Solana token.
    Prioritizes Dexscreener, falls back to Birdeye + Jupiter token list.

    Args:
        token_address: Solana token mint address.

    Returns:
        Dict with token stats or None if failed.
    """
    try:
        # Validate address
        if not (40 <= len(token_address) <= 44):
            logger.error(f"Invalid Solana address length: {token_address}")
            return None
        try:
            PublicKey(token_address)
        except ValueError:
            logger.error(f"Invalid Solana address format: {token_address}")
            return None

        async with aiohttp.ClientSession() as session:
            # Try Dexscreener first
            dexscreener_url = f"{DEXSCREENER_API}/{token_address}"
            try:
                async with session.get(dexscreener_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        pair = data["pairs"][0] if data.get("pairs") else None
                        if pair and pair["chainId"] == "solana":
                            token_info = {
                                "name": pair["baseToken"]["name"],
                                "symbol": pair["baseToken"]["symbol"],
                                "price_usd": float(pair["priceUsd"]),
                                "liquidity": float(pair["liquidity"]["usd"]),
                                "market_cap": float(pair.get("marketCap", pair.get("fdv", 0)))
                            }
                            logger.info(f"Fetched Solana token info from Dexscreener for {token_address}")
                            return token_info
                        else:
                            logger.warning(f"No Solana pairs found on Dexscreener for {token_address}")
                    else:
                        logger.warning(f"Dexscreener API returned {resp.status} for {token_address}")
            except Exception as e:
                logger.error(f"Dexscreener fetch failed for {token_address}: {str(e)}")

            # Fallback to Birdeye for price
            logger.info(f"Attempting Birdeye fallback for {token_address}")
            birdeye_url = f"{BIRDEYE_API}?address={token_address}"
            headers = {"X-API-KEY": BIRDEYE_API_KEY}
            try:
                async with session.get(birdeye_url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("success") and "data" in data:
                            price_usd = float(data["data"]["value"])
                        else:
                            logger.warning(f"Birdeye returned no data for {token_address}")
                            raise ValueError("No price data")
                    else:
                        logger.warning(f"Birdeye API returned {resp.status} for {token_address}")
                        raise ValueError("Bad response")
            except Exception as e:
                logger.error(f"Birdeye fetch failed for {token_address}: {str(e)}")
                # Final fallback to Jupiter for price
                quote_url = f"{JUPITER_API}/quote?inputMint={SOL_MINT}&outputMint={token_address}&amount=1000000&slippageBps=50"
                async with session.get(quote_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status != 200:
                        logger.error(f"Jupiter quote failed: {await resp.text()}")
                        return None
                    quote = await resp.json()
                    price_usd = float(quote["outAmount"]) / 1_000_000 * 150  # Stub SOL at $150

            # Fetch name/symbol from Jupiter token list
            token_list_url = "https://token.jup.ag/strict"
            async with session.get(token_list_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    logger.error(f"Jupiter token list failed: {await resp.text()}")
                    return None
                tokens = await resp.json()
                for token in tokens:
                    if token["address"] == token_address:
                        name, symbol = token["name"], token["symbol"]
                        break
                else:
                    name, symbol = "Unknown", "UNK"

            token_info = {
                "name": name,
                "symbol": symbol,
                "price_usd": price_usd,
                "liquidity": 0,  # Stub; Birdeye free tier doesn’t provide
                "market_cap": 0  # Stub; needs supply or paid API
            }
            logger.info(f"Fetched Solana token info from Birdeye/Jupiter fallback for {token_address}")
            return token_info

    except Exception as e:
        logger.error(f"Failed to fetch Solana token info for {token_address}: {str(e)}")
        return None