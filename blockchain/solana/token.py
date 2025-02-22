import logging
import aiohttp
from solana.publickey import PublicKey
from typing import Dict, Optional
import os

logger = logging.getLogger(__name__)

DEXSCREENER_API = "https://api.dexscreener.com/latest/dex/tokens"
JUPYTER_PRICE_API = "https://api.jup.ag/price/v2"
JUPYTER_TOKEN_API = "https://api.jup.ag/tokens/v1/token"
JUPITER_SWAP_QUOTE_API = "https://api.jup.ag/swap/v1/quote"
SOL_MINT = "So11111111111111111111111111111111111111112"

JUPITER_API_KEY = os.getenv("JUPITER_API_KEY", None)

async def get_sol_price(session: aiohttp.ClientSession) -> float:
    """Fetch the current SOL price in USD from Jupiter Price API."""
    url = f"{JUPYTER_PRICE_API}?mints={SOL_MINT}"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data.get("data") and SOL_MINT in data["data"]:
                    sol_price = float(data["data"][SOL_MINT]["price"])
                    logger.info(f"Fetched SOL price: ${sol_price}")
                    return sol_price
                else:
                    logger.warning("No SOL price data from Jupiter")
            logger.warning(f"Jupiter Price API for SOL returned {resp.status}")
    except Exception as e:
        logger.error(f"Failed to fetch SOL price: {str(e)}")
    return 150.0  # Fallback to $150 if API fails

async def get_solana_token_info(token_address: str) -> Optional[Dict]:
    try:
        if not (40 <= len(token_address) <= 44):
            logger.error(f"Invalid Solana address length: {token_address}")
            return None
        try:
            PublicKey(token_address)
        except ValueError:
            logger.error(f"Invalid Solana address format: {token_address}")
            return None

        async with aiohttp.ClientSession() as session:
            # Fetch SOL price once for all calculations
            sol_price_usd = await get_sol_price(session)

            token_info = await fetch_from_dexscreener(session, token_address, sol_price_usd)
            if token_info:
                logger.info(f"Fetched Solana token info from Dexscreener for {token_address}")
                return token_info

            if JUPITER_API_KEY:
                token_info = await fetch_from_jupiter_authenticated(session, token_address, sol_price_usd)
                if token_info:
                    logger.info(f"Fetched detailed Solana token info from Jupiter (authenticated) for {token_address}")
                    return token_info
            else:
                token_info = await fetch_from_jupiter_free(session, token_address, sol_price_usd)
                if token_info:
                    logger.info(f"Fetched Solana token info from Jupiter (free tier) for {token_address}")
                    return token_info

            logger.error(f"No token info found for {token_address}")
            return None

    except Exception as e:
        logger.error(f"Failed to fetch Solana token info for {token_address}: {str(e)}")
        return None

async def fetch_from_dexscreener(session: aiohttp.ClientSession, token_address: str, sol_price_usd: float) -> Optional[Dict]:
    url = f"{DEXSCREENER_API}/{token_address}"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status == 200:
                data = await resp.json()
                pair = data["pairs"][0] if data.get("pairs") else None
                if pair:
                    liquidity = pair.get("liquidity", {}).get("usd", 0.0)
                    price_usd = float(pair["priceUsd"])
                    trade_amount_usd = 0.01 * sol_price_usd  # 0.01 SOL trade
                    price_impact = (trade_amount_usd / (liquidity + trade_amount_usd)) * 100 if liquidity > 0 else 100.0
                    token_info = {
                        "name": pair["baseToken"]["name"],
                        "symbol": pair["baseToken"]["symbol"],
                        "address": token_address,
                        "price_usd": price_usd,
                        "liquidity": liquidity,
                        "market_cap": float(pair.get("marketCap", pair.get("fdv", 0))),
                        "price_impact": min(price_impact, 100.0)
                    }
                    return token_info
            logger.warning(f"Dexscreener returned {resp.status} for {token_address}")
            return None
    except Exception as e:
        logger.error(f"Dexscreener failed for {token_address}: {str(e)}")
        return None

async def fetch_from_jupiter_authenticated(session: aiohttp.ClientSession, token_address: str, sol_price_usd: float) -> Optional[Dict]:
    url = f"{JUPITER_SWAP_QUOTE_API}?inputMint={SOL_MINT}&outputMint={token_address}&amount=1000000&slippageBps=50"
    headers = {"Authorization": f"Bearer {JUPITER_API_KEY}"}
    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status == 200:
                data = await resp.json()
                price_usd = float(data["outAmount"]) / 1_000_000 * sol_price_usd
                price_impact = float(data.get("priceImpactPct", 0.0)) * 100
                
                token_url = f"{JUPITER_TOKEN_API}/{token_address}"
                async with session.get(token_url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as token_resp:
                    if token_resp.status == 200:
                        token_data = await token_resp.json()
                        name = token_data.get("name", "Unknown")
                        symbol = token_data.get("symbol", "UNK")
                    else:
                        name, symbol = "Unknown", "UNK"
                        logger.warning(f"Jupiter Token API returned {token_resp.status}")

                return {
                    "name": name,
                    "symbol": symbol,
                    "address": token_address,
                    "price_usd": price_usd,
                    "liquidity": 0,
                    "market_cap": 0,
                    "price_impact": price_impact
                }
            logger.error(f"Jupiter Swap API returned {resp.status}")
            return None
    except Exception as e:
        logger.error(f"Jupiter authenticated fetch failed: {str(e)}")
        return None

async def fetch_from_jupiter_free(session: aiohttp.ClientSession, token_address: str, sol_price_usd: float) -> Optional[Dict]:
    price_url = f"{JUPYTER_PRICE_API}?mints={token_address}"
    token_url = f"{JUPYTER_TOKEN_API}/{token_address}"
    
    price_usd = 0.0
    name, symbol = "Unknown", "UNK"
    
    try:
        async with session.get(price_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data.get("data") and token_address in data["data"]:
                    price_usd = float(data["data"][token_address]["price"])
                else:
                    logger.warning(f"No price data from Jupiter free tier")
            else:
                logger.warning(f"Jupiter Price API returned {resp.status}")
    except Exception as e:
        logger.error(f"Jupiter Price API (free) failed: {str(e)}")

    try:
        async with session.get(token_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status == 200:
                data = await resp.json()
                name = data.get("name", "Unknown")
                symbol = data.get("symbol", "UNK")
            else:
                logger.warning(f"Jupiter Token API returned {resp.status}")
    except Exception as e:
        logger.error(f"Jupiter Token API (free) failed: {str(e)}")

    if price_usd > 0 or name != "Unknown":
        trade_amount_usd = 0.01 * sol_price_usd
        assumed_liquidity = 100.0
        price_impact = (trade_amount_usd / (assumed_liquidity + trade_amount_usd)) * 100
        return {
            "name": name,
            "symbol": symbol,
            "address": token_address,
            "price_usd": price_usd,
            "liquidity": 0,
            "market_cap": 0,
            "price_impact": min(price_impact, 100.0)
        }
    return None