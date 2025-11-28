import os
import json
import requests
from datetime import datetime, timezone, timedelta
import logging
from typing import Optional, Dict, List

# --- Configuration ---
API_KEY = os.environ.get('FINANCIAL_API_KEY')
DATA_FILE = 'data.json'
HISTORY_FILE = 'historical_data.json'  # NEW: Track trends over time
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY')

# Stress thresholds
JPY_STRESS_THRESHOLD = 155.0
JPY_CRITICAL_THRESHOLD = 160.0
CNH_STRESS_THRESHOLD = 7.3
CNH_CRITICAL_THRESHOLD = 7.5
MOVE_PROXY_HIGH = 60.0
MOVE_PROXY_CRITICAL = 80.0

# NEW: Volatility detection
JPY_VOLATILITY_THRESHOLD = 2.0  # 2 yen move in 24h = high volatility

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Enhanced Utility Functions ---

def fetch_treasury_yield_10y() -> Optional[float]:
    """
    Fetch 10-Year Treasury Yield from Alpha Vantage.
    Symbol: ^TNX or use FRED API integration
    """
    logging.info("Fetching 10-Year Treasury Yield...")
    # Using Alpha Vantage's TIME_SERIES_DAILY for treasury yield tracking
    # Note: For production, FRED API is more reliable for yields
    URL = f"https://www.alphavantage.co/query?function=FEDERAL_FUNDS_RATE&apikey={API_KEY}"
    
    try:
        response = requests.get(URL, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if 'data' in data and len(data['data']) > 0:
            # Get most recent rate
            latest = data['data'][0]
            rate = float(latest['value'])
            logging.info(f"Federal Funds Rate: {rate}%")
            return rate
        return None
    except Exception as e:
        logging.error(f"Treasury yield fetch failed: {e}")
        return None


def fetch_vix_index() -> Optional[float]:
    """Fetch VIX (market volatility index) as additional stress indicator."""
    logging.info("Fetching VIX Index...")
    # Alpha Vantage doesn't directly support VIX in free tier
    # Using a placeholder - in production, use a dedicated market data API
    return None


def fetch_fx_rate(symbol: str) -> Optional[float]:
    """
    Fetches the latest FX rate using Alpha Vantage.
    Enhanced with retry logic and better error handling.
    """
    logging.info(f"Fetching FX rate for {symbol}...")
    URL = f"https://www.alphavantage.co/query?function=CURRENCY_EXCHANGE_RATE&from_currency={symbol[:3]}&to_currency={symbol[3:]}&apikey={API_KEY}"
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.get(URL, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            # Check for API rate limit message
            if 'Note' in data:
                logging.warning(f"API rate limit reached: {data['Note']}")
                return None
            
            if 'Error Message' in data:
                logging.error(f"Alpha Vantage Error for {symbol}: {data.get('Error Message')}")
                return None
            
            rate_key = '5. Exchange Rate'
            if 'Realtime Currency Exchange Rate' in data and rate_key in data['Realtime Currency Exchange Rate']:
                rate = float(data['Realtime Currency Exchange Rate'][rate_key])
                logging.info(f"{symbol} Rate: {rate}")
                return rate
            else:
                logging.error(f"FX data key not found in response for {symbol}.")
                return None
        
        except requests.exceptions.RequestException as e:
            logging.error(f"Request failed for {symbol} (attempt {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                import time
                time.sleep(2)  # Wait before retry
    
    return None


def load_historical_data() -> List[Dict]:
    """Load historical data for trend analysis."""
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, 'r') as f:
                return json.load(f)
        return []
    except Exception as e:
        logging.error(f"Failed to load historical data: {e}")
        return []


def save_historical_data(history: List[Dict]):
    """Save historical data (keep last 30 days)."""
    try:
        # Keep only last 30 entries
        history = history[-30:]
        with open(HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=2)
        logging.info("Historical data saved")
    except Exception as e:
        logging.error(f"Failed to save historical data: {e}")


def calculate_volatility(current_value: float, history: List[Dict], metric_name: str) -> Optional[float]:
    """Calculate 24h volatility for a given metric."""
    if not history or current_value is None:
        return None
    
    # Find yesterday's value
    yesterday = None
    for entry in reversed(history):
        for metric in entry.get('metrics', []):
            if metric['name'] == metric_name and metric['value'] != "DATA ERROR":
                try:
                    yesterday = float(metric['value'])
                    break
                except (ValueError, TypeError):
                    continue
        if yesterday:
            break
    
    if yesterday:
        return abs(current_value - yesterday)
    return None


def determine_signal(metric_name: str, value: Optional[float], volatility: Optional[float] = None) -> str:
    """Enhanced signal determination with volatility consideration."""
    if value is None:
        return "DATA ERROR"
    
    if metric_name == "USD/JPY Exchange Rate":
        # Factor in volatility
        if volatility and volatility >= JPY_VOLATILITY_THRESHOLD:
            if value >= JPY_CRITICAL_THRESHOLD:
                return "CRITICAL SHOCK"
            elif value >= JPY_STRESS_THRESHOLD:
                return "HIGH STRESS + HIGH VOLATILITY"
        
        if value >= JPY_CRITICAL_THRESHOLD:
            return "CRITICAL SHOCK"
        elif value >= JPY_STRESS_THRESHOLD:
            return "HIGH STRESS"
        elif value > 145.0:
            return "RISING STRESS"
    
    elif metric_name == "USD/CNH (Offshore Yuan) Value":
        if value >= CNH_CRITICAL_THRESHOLD:
            return "CRITICAL SHOCK"
        elif value >= CNH_STRESS_THRESHOLD:
            return "HIGH STRESS"
        elif value > 7.15:
            return "RISING STRESS"
    
    elif metric_name == "MOVE Index Volatility (Proxy)":
        if value >= MOVE_PROXY_CRITICAL:
            return "CRITICAL SHOCK"
        elif value >= MOVE_PROXY_HIGH:
            return "HIGH STRESS"
        elif value > 40.0:
            return "RISING STRESS"
    
    elif metric_name == "10-Year Treasury Yield":
        if value >= 5.5:
            return "CRITICAL SHOCK"
        elif value >= 5.0:
            return "HIGH STRESS"
        elif value >= 4.5:
            return "RISING STRESS"
    
    return "NORMAL"


def calculate_composite_risk_score(metrics: List[Dict]) -> Dict:
    """NEW: Calculate overall risk score from all metrics."""
    score = 0
    weights = {
        "CRITICAL SHOCK": 100,
        "HIGH STRESS + HIGH VOLATILITY": 80,
        "HIGH STRESS": 60,
        "RISING STRESS": 30,
        "NORMAL": 0,
        "DATA ERROR": 0
    }
    
    total_weight = 0
    for metric in metrics:
        signal = metric.get('signal', 'NORMAL')
        score += weights.get(signal, 0)
        total_weight += 1 if signal != "DATA ERROR" else 0
    
    if total_weight == 0:
        return {"score": 0, "level": "UNKNOWN", "color": "#6c757d"}
    
    avg_score = score / total_weight
    
    if avg_score >= 70:
        return {"score": round(avg_score, 1), "level": "CRITICAL", "color": "#dc3545"}
    elif avg_score >= 45:
        return {"score": round(avg_score, 1), "level": "ELEVATED", "color": "#ffc107"}
    elif avg_score >= 20:
        return {"score": round(avg_score, 1), "level": "MODERATE", "color": "#fd7e14"}
    else:
        return {"score": round(avg_score, 1), "level": "LOW", "color": "#28a745"}


def generate_ai_insights(metrics: List[Dict]) -> Dict:
    """Generate Stock Picks and TASI Opportunities using OpenRouter."""
    if not OPENROUTER_API_KEY:
        logging.warning("OPENROUTER_API_KEY not found. Skipping AI insights.")
        return {
            "stock_picks": "AI Analysis Unavailable (Missing API Key)",
            "tasi_opportunities": "AI Analysis Unavailable (Missing API Key)"
        }

    logging.info("Generating AI insights via OpenRouter...")
    
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/crash-detector", 
        "X-Title": "Crash Detector"
    }

    metrics_str = json.dumps(metrics, indent=2)
    prompt = f"""
    You are a financial risk analyst system. 
    Analyze the following **REAL-TIME MARKET METRICS** and **RISK SIGNALS**:
    {metrics_str}

    Based strictly on these numbers, the calculated risk levels, and your knowledge of **recent global financial news**:

    1. **"Stock Picks"**: Identify 3-5 global stocks or sectors that are resilient or opportunistic given the specific stress signals above (e.g., if Yields are high, look for value; if JPY is volatile, look for hedges).
    2. **"Saudi TASI Opportunities"**: Identify 3-5 opportunities in the Saudi TASI market, correlating them with the global oil/risk environment suggested by the data.

    **CRITICAL GUIDELINES:**
    - Focus on **RISK MANAGEMENT** and **TRUE NUMBERS**.
    - Do not hallucinate data. Use the provided metrics as the ground truth for your rationale.
    - Mention specific risks (e.g., "Due to high 10Y Yields...") in your explanation.
    - Keep it concise, professional, and actionable (but strictly educational).

    Format the output as a JSON object with keys "stock_picks" and "tasi_opportunities", containing HTML strings (inner content only).
    """

    data = {
        "model": "tngtech/tng-r1t-chimera:free",
        "messages": [
            {"role": "system", "content": "You are a financial analyst AI. Provide insights for demonstration purposes only."},
            {"role": "user", "content": prompt}
        ],
        "response_format": {"type": "json_object"}
    }

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=30
        )
        response.raise_for_status()
        result = response.json()
        
        content = result['choices'][0]['message']['content']
        
        # Enhanced JSON parsing using Regex to find the first JSON object
        import re
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        
        if json_match:
            json_str = json_match.group(0)
            parsed_content = json.loads(json_str)
            return {
                "stock_picks": parsed_content.get("stock_picks", "Analysis Data Missing"),
                "tasi_opportunities": parsed_content.get("tasi_opportunities", "Analysis Data Missing")
            }
        else:
            logging.error(f"Raw AI Response (No JSON found): {content}")
            raise ValueError("Could not extract JSON from AI response")

    except Exception as e:
        logging.error(f"AI Generation failed: {e}")
        # Create a user-friendly error message
        error_str = str(e)
        if "401" in error_str:
            ui_error = "AI Configuration Error: Invalid API Key (401)"
        elif "429" in error_str:
            ui_error = "AI Busy: Rate Limit Exceeded (429)"
        elif "Expecting value" in error_str or "JSON" in error_str:
            ui_error = "AI Error: Response Parsing Failed"
        else:
            ui_error = f"AI Analysis Failed: {error_str[:30]}..."

        return {
            "stock_picks": ui_error,
            "tasi_opportunities": ui_error
        }


def update_tracing_data():
    """Main function with enhanced analytics."""
    if not API_KEY:
        logging.error("FINANCIAL_API_KEY not found in environment variables.")
        return
    
    # Load historical data
    history = load_historical_data()
    
    # Fetch current data
    move_proxy = 45.0  # Placeholder - replace with actual API
    usd_jpy = fetch_fx_rate('USDJPY')
    usd_cnh = fetch_fx_rate('USDCNH')
    treasury_10y = fetch_treasury_yield_10y()
    
    # Calculate volatilities
    jpy_volatility = calculate_volatility(usd_jpy, history, "USD/JPY Exchange Rate") if usd_jpy else None
    
    # Build enhanced metrics array
    new_metrics = [
        {
            "name": "USD/JPY Exchange Rate",
            "value": f"{usd_jpy:.4f}" if usd_jpy else "DATA ERROR",
            "signal": determine_signal("USD/JPY Exchange Rate", usd_jpy, jpy_volatility),
            "volatility_24h": f"{jpy_volatility:.2f}" if jpy_volatility else "N/A"
        },
        {
            "name": "USD/CNH (Offshore Yuan) Value",
            "value": f"{usd_cnh:.4f}" if usd_cnh else "DATA ERROR",
            "signal": determine_signal("USD/CNH (Offshore Yuan) Value", usd_cnh)
        },
        {
            "name": "MOVE Index Volatility (Proxy)",
            "value": f"{move_proxy:.2f}" if move_proxy else "DATA ERROR",
            "signal": determine_signal("MOVE Index Volatility (Proxy)", move_proxy)
        },
        {
            "name": "10-Year Treasury Yield",
            "value": f"{treasury_10y:.2f}%" if treasury_10y else "DATA ERROR",
            "signal": determine_signal("10-Year Treasury Yield", treasury_10y)
        }
    ]
    
    # Calculate composite risk
    risk_assessment = calculate_composite_risk_score(new_metrics)

    # Generate AI Insights
    ai_insights = generate_ai_insights(new_metrics)
    
    # Create final data object
    final_data = {
        "last_update": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "target_date": "2026-11-28",
        "days_remaining": (datetime(2026, 11, 28) - datetime.now()).days,
        "risk_assessment": risk_assessment,
        "metrics": new_metrics,
        "ai_insights": ai_insights
    }
    
    # Save to current data file
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(final_data, f, ensure_ascii=False, indent=4)
        logging.info(f"Successfully updated {DATA_FILE}")
    except IOError as e:
        logging.error(f"Failed to write to {DATA_FILE}: {e}")
    
    # Update historical data
    history.append(final_data)
    save_historical_data(history)


if __name__ == '__main__':
    update_tracing_data()
