import os
import json
import requests
from datetime import datetime, timezone, timedelta
import logging
from typing import Optional, Dict, List, Tuple
import yfinance as yf

# --- Configuration ---
DATA_FILE = 'data.json'
HISTORY_FILE = 'historical_data.json'
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY')

# Stress thresholds
JPY_STRESS_THRESHOLD = 150.0
JPY_CRITICAL_THRESHOLD = 155.0
CNH_STRESS_THRESHOLD = 7.25
CNH_CRITICAL_THRESHOLD = 7.4
MOVE_PROXY_HIGH = 120.0  # Adjusted for actual MOVE index levels if available, or VIX proxy
MOVE_PROXY_CRITICAL = 140.0

# Auction Thresholds
AUCTION_BTC_STRESS = 2.3  # Bid-to-Cover Ratio

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Data Fetching Functions ---

def fetch_treasury_auction_data(term: str, security_type: str) -> Optional[Dict]:
    """
    Fetch latest Treasury Auction data from FiscalData API.
    """
    logging.info(f"Fetching {term} Treasury Auction data...")
    base_url = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query"
    
    # Filter for specific term and type, sort by date desc
    params = {
        "filter": f"security_term:eq:{term},security_type:eq:{security_type}",
        "sort": "-auction_date",
        "page[size]": 1
    }
    
    try:
        response = requests.get(base_url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if 'data' in data and len(data['data']) > 0:
            return data['data'][0]
        return None
    except Exception as e:
        logging.error(f"Treasury Auction fetch failed for {term}: {e}")
        return None

def fetch_market_data_yf(ticker: str) -> Optional[float]:
    """Fetch current price/rate using yfinance."""
    logging.info(f"Fetching {ticker} via yfinance...")
    try:
        ticker_obj = yf.Ticker(ticker)
        # Try to get fast info first
        price = None
        
        # Method 1: fast_info (often works for currencies/indices)
        try:
            price = ticker_obj.fast_info.last_price
        except:
            pass
            
        # Method 2: history (fallback)
        if price is None:
            hist = ticker_obj.history(period="1d")
            if not hist.empty:
                price = hist['Close'].iloc[-1]
                
        if price is not None:
            logging.info(f"{ticker}: {price}")
            return float(price)
        
        logging.warning(f"No data found for {ticker}")
        return None
    except Exception as e:
        logging.error(f"yfinance failed for {ticker}: {e}")
        return None

def fetch_financial_news() -> List[Dict]:
    """Fetch latest financial news from free RSS feeds."""
    logging.info("Fetching financial news from RSS feeds...")
    rss_feeds = [
        "https://finance.yahoo.com/news/rssindex",
        "https://www.reuters.com/business/finance/rss",
        "https://www.marketwatch.com/rss/topstories",
    ]
    
    all_articles = []
    try:
        import feedparser
        for feed_url in rss_feeds:
            try:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries[:3]:
                    all_articles.append({
                        "title": entry.get('title', 'No title'),
                        "source": feed.feed.get('title', 'Unknown'),
                        "publishedAt": entry.get('published', 'Unknown date')
                    })
            except Exception:
                continue
        return all_articles[:5]
    except ImportError:
        return []
    except Exception as e:
        logging.error(f"RSS fetch failed: {e}")
        return []

# --- Analysis Functions ---

def load_historical_data() -> List[Dict]:
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, 'r') as f:
                return json.load(f)
        return []
    except Exception:
        return []

def save_historical_data(history: List[Dict]):
    try:
        history = history[-30:]
        with open(HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        logging.error(f"Failed to save history: {e}")

def determine_signal(metric_name: str, value: float, extra_data: Dict = None) -> str:
    """Determine stress signal based on thresholds."""
    if value is None:
        return "DATA ERROR"
    
    # 1. USD/JPY
    if metric_name == "USD/JPY":
        if value >= JPY_CRITICAL_THRESHOLD: return "CRITICAL SHOCK"
        if value >= JPY_STRESS_THRESHOLD: return "HIGH STRESS"
        if value > 145.0: return "RISING STRESS"
        
    # 2. USD/CNH
    elif metric_name == "USD/CNH":
        if value >= CNH_CRITICAL_THRESHOLD: return "CRITICAL SHOCK"
        if value >= CNH_STRESS_THRESHOLD: return "HIGH STRESS"
        if value > 7.15: return "RISING STRESS"
        
    # 3. 10-Year Yield
    elif metric_name == "10Y Treasury Yield":
        if value >= 5.0: return "CRITICAL SHOCK"
        if value >= 4.5: return "HIGH STRESS"
        if value >= 4.2: return "RISING STRESS"
        
    # 4. MOVE Index (Volatility)
    elif metric_name == "MOVE Index":
        if value >= MOVE_PROXY_CRITICAL: return "CRITICAL SHOCK"
        if value >= MOVE_PROXY_HIGH: return "HIGH STRESS"
        if value > 100.0: return "RISING STRESS"

    # 5. Auction Bid-to-Cover
    elif metric_name == "10Y Auction Bid-to-Cover":
        if value < 2.0: return "CRITICAL SHOCK"
        if value < AUCTION_BTC_STRESS: return "HIGH STRESS" # < 2.3
        if value < 2.4: return "RISING STRESS"
        
    # 6. China Credit Proxy (CBON ETF) - Lower is worse (outflows/yields up)
    elif metric_name == "China Credit Proxy (CBON)":
        # Assuming baseline ~21.0-22.0. Drop indicates stress.
        if value < 20.0: return "HIGH STRESS"
        
    return "NORMAL"

def calculate_composite_risk(metrics: List[Dict]) -> Dict:
    score = 0
    count = 0
    weights = {"CRITICAL SHOCK": 100, "HIGH STRESS": 75, "RISING STRESS": 40, "NORMAL": 0}
    
    for m in metrics:
        if m['signal'] in weights:
            score += weights[m['signal']]
            count += 1
            
    if count == 0: return {"score": 0, "level": "UNKNOWN", "color": "#6c757d"}
    
    avg = score / count
    if avg >= 60: return {"score": round(avg, 1), "level": "CRITICAL", "color": "#dc3545"}
    if avg >= 35: return {"score": round(avg, 1), "level": "ELEVATED", "color": "#ffc107"}
    return {"score": round(avg, 1), "level": "LOW", "color": "#28a745"}

def generate_ai_insights(metrics: List[Dict]) -> Dict:
    if not OPENROUTER_API_KEY:
        return {"crash_analysis": "AI Key Missing", "news_summary": "AI Key Missing"}
        
    news = fetch_financial_news()
    news_text = "\n".join([f"- {n['title']}" for n in news])
    
    metrics_str = json.dumps(metrics, indent=2)
    
    prompt = f"""
    Analyze these market metrics for a "Global Financial Fault Lines" convergence event.
    
    **THEORY:**
    A crash is triggered by the simultaneous convergence of:
    1. **US Treasury Funding Shock** (Weak Auctions, Rising Yields)
    2. **Japan Carry-Trade Unwind** (USD/JPY Crash/Spike)
    3. **China Credit Crisis** (LGFV Defaults, Yuan Devaluation)
    
    **METRICS:**
    {metrics_str}
    
    **NEWS:**
    {news_text}
    
    **TASK:**
    1. Check for **SIMULTANEOUS MOVEMENT**: Are Yields, USD/JPY, and USD/CNH all moving in stress directions?
    2. Analyze the **10Y Auction Bid-to-Cover**: Is demand failing (< 2.3x)?
    3. Analyze **China Credit**: Is the LGFV proxy showing stress?
    
    Return JSON:
    {{
        "crash_analysis": "HTML string (<ul><li>) with analysis. Highlight the 'Convergence Status'.",
        "news_summary": "HTML string summarizing key news."
    }}
    """
    
    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
            json={
                "model": "tngtech/tng-r1t-chimera:free",
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"}
            },
            timeout=30
        )
        content = resp.json()['choices'][0]['message']['content']
        # Simple JSON extraction
        start = content.find('{')
        end = content.rfind('}') + 1
        return json.loads(content[start:end])
    except Exception as e:
        logging.error(f"AI Error: {e}")
        return {"crash_analysis": "AI Analysis Failed", "news_summary": "Check Logs"}

def update_tracing_data():
    # 1. Fetch Data
    # Yahoo Finance Tickers
    usd_jpy = fetch_market_data_yf("JPY=X")
    usd_cnh = fetch_market_data_yf("CNH=X")
    yield_10y = fetch_market_data_yf("^TNX")  # CBOE 10 Year Treasury Yield
    move_index = fetch_market_data_yf("^MOVE") # ICE BofA MOVE Index (might not be free on Yahoo, fallback to VIX if needed)
    if not move_index:
        move_index = fetch_market_data_yf("^VIX") # Fallback proxy
        move_name = "VIX (Volatility Proxy)"
    else:
        move_name = "MOVE Index"
        
    cbon_etf = fetch_market_data_yf("CBON") # China Bond ETF (LGFV Proxy)
    
    # Treasury Auction Data
    auction_10y = fetch_treasury_auction_data("10-Year", "Note")
    auction_30y = fetch_treasury_auction_data("30-Year", "Bond")
    
    # Process Auction Metrics
    btc_10y = float(auction_10y['bid_to_cover_ratio']) if auction_10y else None
    
    # Calculate 30Y Tail (High Yield - Average Yield) if available
    tail_30y = None
    if auction_30y and 'high_yield' in auction_30y and 'average_median_yield' in auction_30y:
        try:
            high = float(auction_30y['high_yield'])
            avg = float(auction_30y['average_median_yield'])
            tail_30y = (high - avg) * 100 # Basis points
        except:
            pass

    # 2. Build Metrics List
    metrics = [
        {
            "name": "10Y Treasury Auction Bid-to-Cover",
            "value": f"{btc_10y:.2f}x" if btc_10y else "N/A",
            "signal": determine_signal("10Y Auction Bid-to-Cover", btc_10y),
            "desc": "Demand strength (Stress < 2.3x)"
        },
        {
            "name": "30Y Auction Tail",
            "value": f"{tail_30y:.1f} bps" if tail_30y is not None else "N/A",
            "signal": "NORMAL" if (tail_30y is None or tail_30y < 3.0) else "HIGH STRESS",
            "desc": "Dealer reluctance (Stress > 3bps)"
        },
        {
            "name": "USD/JPY",
            "value": f"{usd_jpy:.2f}" if usd_jpy else "N/A",
            "signal": determine_signal("USD/JPY", usd_jpy),
            "desc": "Carry-trade stress"
        },
        {
            "name": "USD/CNH",
            "value": f"{usd_cnh:.4f}" if usd_cnh else "N/A",
            "signal": determine_signal("USD/CNH", usd_cnh),
            "desc": "Yuan stability"
        },
        {
            "name": "China Credit Proxy (CBON)",
            "value": f"${cbon_etf:.2f}" if cbon_etf else "N/A",
            "signal": determine_signal("China Credit Proxy (CBON)", cbon_etf),
            "desc": "LGFV/Bond stress proxy"
        },
        {
            "name": "10Y Treasury Yield",
            "value": f"{yield_10y:.2f}%" if yield_10y else "N/A",
            "signal": determine_signal("10Y Treasury Yield", yield_10y),
            "desc": "Systemic risk trigger"
        },
        {
            "name": move_name,
            "value": f"{move_index:.2f}" if move_index else "N/A",
            "signal": determine_signal("MOVE Index", move_index),
            "desc": "Treasury volatility"
        }
    ]
    
    # 3. Generate Output
    risk = calculate_composite_risk(metrics)
    ai_insights = generate_ai_insights(metrics)
    
    final_data = {
        "last_update": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "risk_assessment": risk,
        "metrics": metrics,
        "ai_insights": ai_insights,
        "days_remaining": (datetime(2026, 11, 28) - datetime.now()).days
    }
    
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(final_data, f, indent=4)
        
    # History
    history = load_historical_data()
    history.append(final_data)
    save_historical_data(history)
    logging.info("Update complete.")

if __name__ == "__main__":
    update_tracing_data()
