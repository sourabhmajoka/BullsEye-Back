"""
BullsEye Stock Service v4
- nsetools: live quotes + gainers/losers/indices (direct NSE)  
- Yahoo Finance Chart API (v8): historical OHLCV - direct HTTP, no yfinance session issues
- Yahoo Finance Quotesummary API: fundamentals - direct HTTP
- Sector data: mapped from industry names
- Full TTL cache to minimize API calls
"""

import time
import threading
import requests
from datetime import datetime, timedelta

# ─── TTL Cache ────────────────────────────────────────────────────────────────

class TTLCache:
    def __init__(self):
        self._d = {}
        self._lock = threading.RLock()

    def get(self, key):
        with self._lock:
            item = self._d.get(key)
            if item and time.time() < item['exp']:
                return item['v']
            if item:
                del self._d[key]
            return None

    def set(self, key, value, ttl=60):
        with self._lock:
            self._d[key] = {'v': value, 'exp': time.time() + ttl}

_cache = TTLCache()

# ─── Shared HTTP session (with browser-like headers) ─────────────────────────

_session = requests.Session()
_session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Origin': 'https://finance.yahoo.com',
    'Referer': 'https://finance.yahoo.com/',
})

def _yf_get(url, params=None, timeout=15):
    """GET request to Yahoo Finance with auto-cookie handling"""
    try:
        # Get a crumb/cookie if needed
        resp = _session.get(url, params=params, timeout=timeout)
        if resp.status_code == 401:
            # Refresh cookies
            _session.get('https://finance.yahoo.com', timeout=10)
            resp = _session.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return None

# ─── NSETools singleton ───────────────────────────────────────────────────────

_nse = None
_nse_lock = threading.Lock()

def _get_nse():
    global _nse
    with _nse_lock:
        if _nse is None:
            try:
                from nsetools import Nse
                _nse = Nse()
            except Exception:
                _nse = False
    return _nse if _nse else None

# ─── Industry → Sector mapping ────────────────────────────────────────────────

INDUSTRY_SECTOR_MAP = {
    # Technology
    'Information Technology Services': 'IT',
    'Software—Application': 'IT',
    'Software—Infrastructure': 'IT',
    'Computer Hardware': 'IT',
    'Electronic Components': 'IT',
    'Semiconductor Equipment & Materials': 'IT',
    'Semiconductors': 'IT',
    # Banking & Finance
    'Banks—Diversified': 'Banking',
    'Banks—Regional': 'Banking',
    'Insurance—Life': 'Finance',
    'Insurance—Property & Casualty': 'Finance',
    'Financial Data & Stock Exchanges': 'Finance',
    'Capital Markets': 'Finance',
    'Asset Management': 'Finance',
    'Consumer Finance': 'Finance',
    'Credit Services': 'Finance',
    'Mortgage Finance': 'Finance',
    # Pharma
    'Drug Manufacturers—Specialty & Generic': 'Pharma',
    'Drug Manufacturers—General': 'Pharma',
    'Biotechnology': 'Pharma',
    'Medical Devices': 'Healthcare',
    'Medical Care Facilities': 'Healthcare',
    'Health Information Services': 'Healthcare',
    # Auto
    'Auto Manufacturers': 'Auto',
    'Auto Parts': 'Auto',
    'Auto & Truck Dealerships': 'Auto',
    # Energy
    'Oil & Gas Integrated': 'Energy',
    'Oil & Gas E&P': 'Energy',
    'Oil & Gas Refining & Marketing': 'Energy',
    'Utilities—Regulated Electric': 'Energy',
    'Utilities—Diversified': 'Energy',
    'Solar': 'Energy',
    # FMCG
    'Household & Personal Products': 'FMCG',
    'Packaged Foods': 'FMCG',
    'Beverages—Non-Alcoholic': 'FMCG',
    'Beverages—Alcoholic': 'FMCG',
    'Tobacco': 'FMCG',
    # Metal & Mining
    'Steel': 'Metals',
    'Other Industrial Metals & Mining': 'Metals',
    'Aluminum': 'Metals',
    'Copper': 'Metals',
    'Specialty Chemicals': 'Chemicals',
    'Agricultural Inputs': 'Chemicals',
    'Basic Materials': 'Materials',
    # Real Estate
    'Real Estate—Development': 'Real Estate',
    'Real Estate Services': 'Real Estate',
    # Telecom
    'Telecom Services': 'Telecom',
    'Communication Equipment': 'Telecom',
    # Infrastructure
    'Engineering & Construction': 'Infra',
    'Industrial Distribution': 'Infra',
    'Specialty Industrial Machinery': 'Infra',
    'Electrical Equipment & Parts': 'Infra',
    'Aerospace & Defense': 'Defense',
    # Consumer
    'Specialty Retail': 'Consumer',
    'Department Stores': 'Consumer',
    'Apparel Retail': 'Consumer',
    'Apparel Manufacturing': 'Consumer',
    'Luxury Goods': 'Consumer',
    'Entertainment': 'Media',
    'Broadcasting': 'Media',
    'Restaurants': 'Consumer',
    'Travel & Leisure': 'Consumer',
    'Transportation & Logistics': 'Logistics',
}

def _get_sector(industry, sector_from_yf=None):
    """Map industry to clean sector name"""
    if industry and industry in INDUSTRY_SECTOR_MAP:
        return INDUSTRY_SECTOR_MAP[industry]
    if sector_from_yf and sector_from_yf not in ('N/A', '', None):
        # Clean up YF sector names
        s = sector_from_yf
        if 'Technology' in s: return 'IT'
        if 'Financial' in s or 'Bank' in s: return 'Banking'
        if 'Health' in s or 'Pharma' in s or 'Drug' in s: return 'Pharma'
        if 'Consumer' in s and 'Staple' in s: return 'FMCG'
        if 'Consumer' in s: return 'Consumer'
        if 'Energy' in s or 'Oil' in s: return 'Energy'
        if 'Material' in s or 'Metal' in s or 'Mining' in s: return 'Metals'
        if 'Utility' in s or 'Power' in s: return 'Energy'
        if 'Industrial' in s: return 'Infra'
        if 'Telecom' in s or 'Communication' in s: return 'Telecom'
        if 'Real Estate' in s: return 'Real Estate'
        return s
    return 'N/A'

# ─── Hardcoded sector map for common Indian stocks ────────────────────────────

STOCK_SECTOR = {
    # IT
    'TCS': 'IT', 'INFY': 'IT', 'WIPRO': 'IT', 'HCLTECH': 'IT',
    'TECHM': 'IT', 'PERSISTENT': 'IT', 'MPHASIS': 'IT', 'LTIM': 'IT',
    'LTTS': 'IT', 'OFSS': 'IT', 'KPITTECH': 'IT', 'HAPPSTMNDS': 'IT',
    # Banking
    'HDFCBANK': 'Banking', 'ICICIBANK': 'Banking', 'SBIN': 'Banking',
    'KOTAKBANK': 'Banking', 'AXISBANK': 'Banking', 'INDUSINDBK': 'Banking',
    'BANKBARODA': 'Banking', 'PNB': 'Banking', 'CANBK': 'Banking',
    'FEDERALBNK': 'Banking', 'BANDHANBNK': 'Banking', 'IDFCFIRSTB': 'Banking',
    'UNIONBANK': 'Banking', 'AUBANK': 'Banking',
    # Finance
    'BAJFINANCE': 'Finance', 'BAJAJFINSV': 'Finance', 'HDFCAMC': 'Finance',
    'CHOLAFIN': 'Finance', 'SBICARD': 'Finance', 'PFC': 'Finance',
    'RECLTD': 'Finance', 'LICHSGFIN': 'Finance', 'SBILIFE': 'Finance',
    'HDFCLIFE': 'Finance', 'ICICIGI': 'Finance', 'ICICIPRULI': 'Finance',
    'CDSL': 'Finance', 'JIOFIN': 'Finance', 'IRFC': 'Finance',
    # Pharma
    'SUNPHARMA': 'Pharma', 'DRREDDY': 'Pharma', 'CIPLA': 'Pharma',
    'DIVISLAB': 'Pharma', 'LUPIN': 'Pharma', 'BIOCON': 'Pharma',
    'TORNTPHARM': 'Pharma', 'APOLLOHOSP': 'Healthcare',
    'FORTIS': 'Healthcare',
    # Auto
    'MARUTI': 'Auto', 'TATAMOTORS': 'Auto', 'MM': 'Auto',
    'BAJAJ-AUTO': 'Auto', 'HEROMOTOCO': 'Auto', 'EICHERMOT': 'Auto',
    'TVSMOTOR': 'Auto', 'BOSCHLTD': 'Auto', 'MOTHERSON': 'Auto',
    # Energy & Oil
    'RELIANCE': 'Energy', 'ONGC': 'Energy', 'BPCL': 'Energy',
    'IOC': 'Energy', 'GAIL': 'Energy', 'PETRONET': 'Energy',
    'COALINDIA': 'Energy', 'NTPC': 'Energy', 'POWERGRID': 'Energy',
    'TATAPOWER': 'Energy', 'ADANIGREEN': 'Energy', 'NHPC': 'Energy',
    'SJVN': 'Energy', 'TORNTPOWER': 'Energy', 'CESC': 'Energy',
    'IREDA': 'Energy',
    # FMCG
    'HINDUNILVR': 'FMCG', 'ITC': 'FMCG', 'NESTLEIND': 'FMCG',
    'DABUR': 'FMCG', 'MARICO': 'FMCG', 'COLPAL': 'FMCG',
    'BRITANNIA': 'FMCG', 'GODREJCP': 'FMCG', 'TATACONSUM': 'FMCG',
    # Metals
    'TATASTEEL': 'Metals', 'JSWSTEEL': 'Metals', 'HINDALCO': 'Metals',
    'VEDL': 'Metals', 'SAIL': 'Metals', 'NMDC': 'Metals',
    'APLAPOLLO': 'Metals',
    # Chemicals
    'PIDILITIND': 'Chemicals', 'DEEPAKNTR': 'Chemicals',
    'NAVINFLUOR': 'Chemicals', 'SRF': 'Chemicals', 'PIIND': 'Chemicals',
    'UPL': 'Chemicals', 'SOLARINDS': 'Chemicals',
    # Infra / Construction
    'LT': 'Infra', 'ULTRACEMCO': 'Infra', 'GRASIM': 'Infra',
    'AMBUJACEM': 'Infra', 'HAL': 'Defense', 'BEL': 'Defense',
    'CONCOR': 'Logistics', 'RVNL': 'Infra', 'RAILTEL': 'Infra',
    'IRCTC': 'Logistics',
    # Consumer / Retail
    'TITAN': 'Consumer', 'TRENT': 'Consumer', 'DMART': 'Consumer',
    'PAGEIND': 'Consumer', 'CAMPUS': 'Consumer', 'VOLTAS': 'Consumer',
    'HAVELLS': 'Consumer',
    # Real Estate
    'DLF': 'Real Estate', 'GODREJPROP': 'Real Estate',
    'OBEROIRLTY': 'Real Estate',
    # Telecom
    'BHARTIARTL': 'Telecom', 'TATACOMM': 'Telecom',
    # Media / Entertainment
    'SUNTV': 'Media', 'ZEEL': 'Media', 'PVRINOX': 'Media',
    # Tech / Startup
    'ZOMATO': 'Consumer', 'PAYTM': 'Finance', 'NYKAA': 'Consumer',
    'POLICYBZR': 'Finance', 'DELHIVERY': 'Logistics',
    'NAUKRI': 'Technology', 'INDIGO': 'Logistics',
    # Industrial
    'SIEMENS': 'Infra', 'ABB': 'Infra', 'THERMAX': 'Infra',
    'CUMMINSIND': 'Infra', 'CGPOWER': 'Infra', 'DIXON': 'Technology',
    'KAYNES': 'Technology', 'TIINDIA': 'Auto', 'POLYCAB': 'Infra',
    'SCHAEFFLER': 'Auto', 'HFCL': 'Telecom',
    # Misc
    'ASTRAL': 'Infra', 'TRIDENT': 'Materials',
    'MRF': 'Auto', 'IEX': 'Energy', 'ABCAPITAL': 'Finance',
    'SHRIRAMFIN': 'Finance', 'LICI': 'Finance', 'JIOFIN': 'Finance',
}

# ─── Full master stock list ───────────────────────────────────────────────────

INDIAN_STOCKS = {
    "RELIANCE": "Reliance Industries Ltd", "TCS": "Tata Consultancy Services Ltd",
    "HDFCBANK": "HDFC Bank Ltd", "INFY": "Infosys Ltd", "ICICIBANK": "ICICI Bank Ltd",
    "HINDUNILVR": "Hindustan Unilever Ltd", "ITC": "ITC Ltd", "SBIN": "State Bank of India",
    "BHARTIARTL": "Bharti Airtel Ltd", "KOTAKBANK": "Kotak Mahindra Bank Ltd",
    "LT": "Larsen and Toubro Ltd", "AXISBANK": "Axis Bank Ltd",
    "ASIANPAINT": "Asian Paints Ltd", "MARUTI": "Maruti Suzuki India Ltd",
    "SUNPHARMA": "Sun Pharmaceutical Industries Ltd", "TITAN": "Titan Company Ltd",
    "BAJFINANCE": "Bajaj Finance Ltd", "NESTLEIND": "Nestle India Ltd",
    "WIPRO": "Wipro Ltd", "ULTRACEMCO": "UltraTech Cement Ltd",
    "POWERGRID": "Power Grid Corporation of India", "NTPC": "NTPC Ltd",
    "HCLTECH": "HCL Technologies Ltd", "TECHM": "Tech Mahindra Ltd",
    "BAJAJFINSV": "Bajaj Finserv Ltd", "ONGC": "Oil and Natural Gas Corporation Ltd",
    "COALINDIA": "Coal India Ltd", "TATAMOTORS": "Tata Motors Ltd",
    "TATASTEEL": "Tata Steel Ltd", "ADANIENT": "Adani Enterprises Ltd",
    "ADANIPORTS": "Adani Ports and SEZ Ltd", "JSWSTEEL": "JSW Steel Ltd",
    "HINDALCO": "Hindalco Industries Ltd", "DRREDDY": "Dr Reddys Laboratories Ltd",
    "CIPLA": "Cipla Ltd", "EICHERMOT": "Eicher Motors Ltd",
    "HEROMOTOCO": "Hero MotoCorp Ltd", "APOLLOHOSP": "Apollo Hospitals Enterprise Ltd",
    "GRASIM": "Grasim Industries Ltd", "DIVISLAB": "Divis Laboratories Ltd",
    "BPCL": "Bharat Petroleum Corporation Ltd", "MM": "Mahindra and Mahindra Ltd",
    "BRITANNIA": "Britannia Industries Ltd", "SHRIRAMFIN": "Shriram Finance Ltd",
    "TRENT": "Trent Ltd", "BEL": "Bharat Electronics Ltd",
    "SBILIFE": "SBI Life Insurance Company Ltd", "HDFCLIFE": "HDFC Life Insurance Company Ltd",
    "INDUSINDBK": "IndusInd Bank Ltd", "ADANIGREEN": "Adani Green Energy Ltd",
    "AMBUJACEM": "Ambuja Cements Ltd", "BAJAJ-AUTO": "Bajaj Auto Ltd",
    "BANDHANBNK": "Bandhan Bank Ltd", "BANKBARODA": "Bank of Baroda",
    "BERGEPAINT": "Berger Paints India Ltd", "BIOCON": "Biocon Ltd",
    "BOSCHLTD": "Bosch Ltd", "CANBK": "Canara Bank",
    "CHOLAFIN": "Cholamandalam Investment and Finance", "COLPAL": "Colgate-Palmolive India Ltd",
    "CONCOR": "Container Corporation of India", "DLF": "DLF Ltd",
    "DABUR": "Dabur India Ltd", "FEDERALBNK": "Federal Bank Ltd",
    "GAIL": "GAIL India Ltd", "GODREJCP": "Godrej Consumer Products Ltd",
    "GODREJPROP": "Godrej Properties Ltd", "HDFCAMC": "HDFC Asset Management Company",
    "HAL": "Hindustan Aeronautics Ltd", "HAVELLS": "Havells India Ltd",
    "IDFCFIRSTB": "IDFC First Bank Ltd", "IEX": "Indian Energy Exchange Ltd",
    "IOC": "Indian Oil Corporation Ltd", "IRCTC": "Indian Railway Catering and Tourism",
    "JINDALSTEL": "Jindal Steel and Power Ltd", "JUBLFOOD": "Jubilant Foodworks Ltd",
    "LICHSGFIN": "LIC Housing Finance Ltd", "LUPIN": "Lupin Ltd",
    "MARICO": "Marico Ltd", "MOTHERSON": "Samvardhana Motherson International",
    "MRF": "MRF Ltd", "NAUKRI": "Info Edge India Ltd", "NMDC": "NMDC Ltd",
    "OFSS": "Oracle Financial Services Software", "PAGEIND": "Page Industries Ltd",
    "PERSISTENT": "Persistent Systems Ltd", "PETRONET": "Petronet LNG Ltd",
    "PFC": "Power Finance Corporation Ltd", "PIDILITIND": "Pidilite Industries Ltd",
    "PIIND": "PI Industries Ltd", "PNB": "Punjab National Bank",
    "POLYCAB": "Polycab India Ltd", "RECLTD": "REC Ltd",
    "SAIL": "Steel Authority of India Ltd", "SIEMENS": "Siemens Ltd",
    "SRF": "SRF Ltd", "TATACOMM": "Tata Communications Ltd",
    "TATACONSUM": "Tata Consumer Products Ltd", "TATAPOWER": "Tata Power Company Ltd",
    "TORNTPHARM": "Torrent Pharmaceuticals Ltd", "TVSMOTOR": "TVS Motor Company Ltd",
    "UPL": "UPL Ltd", "VEDL": "Vedanta Ltd", "VOLTAS": "Voltas Ltd",
    "ZOMATO": "Zomato Ltd", "DMART": "Avenue Supermarts Ltd",
    "ABCAPITAL": "Aditya Birla Capital Ltd", "APLAPOLLO": "APL Apollo Tubes Ltd",
    "ASTRAL": "Astral Ltd", "AUBANK": "AU Small Finance Bank Ltd",
    "CDSL": "Central Depository Services", "DEEPAKNTR": "Deepak Nitrite Ltd",
    "DIXON": "Dixon Technologies India Ltd", "HAPPSTMNDS": "Happiest Minds Technologies Ltd",
    "IRFC": "Indian Railway Finance Corporation", "KPITTECH": "KPIT Technologies Ltd",
    "LICI": "Life Insurance Corporation of India", "LTTS": "L and T Technology Services Ltd",
    "LTIM": "LTIMindtree Ltd", "NAVINFLUOR": "Navin Fluorine International Ltd",
    "OBEROIRLTY": "Oberoi Realty Ltd", "SOLARINDS": "Solar Industries India Ltd",
    "SUNTV": "Sun TV Network Ltd", "TATACHEM": "Tata Chemicals Ltd",
    "TATAELXSI": "Tata Elxsi Ltd", "TRIDENT": "Trident Ltd",
    "ZEEL": "Zee Entertainment Enterprises Ltd", "PAYTM": "One 97 Communications Ltd",
    "NYKAA": "FSN E-Commerce Ventures Ltd", "POLICYBZR": "PB Fintech Ltd",
    "INDIGO": "InterGlobe Aviation Ltd", "PVRINOX": "PVR Inox Ltd",
    "UNIONBANK": "Union Bank of India", "MPHASIS": "Mphasis Ltd",
    "ICICIGI": "ICICI Lombard General Insurance", "ICICIPRULI": "ICICI Prudential Life Insurance",
    "SBICARD": "SBI Cards and Payment Services", "JIOFIN": "Jio Financial Services Ltd",
    "CGPOWER": "CG Power and Industrial Solutions", "KAYNES": "Kaynes Technology India Ltd",
    "TORNTPOWER": "Torrent Power Ltd", "NHPC": "NHPC Ltd", "SJVN": "SJVN Ltd",
    "RVNL": "Rail Vikas Nigam Ltd", "RAILTEL": "RailTel Corporation of India",
    "IREDA": "Indian Renewable Energy Development Agency",
    "TIINDIA": "Tube Investments of India Ltd", "CUMMINSIND": "Cummins India Ltd",
    "THERMAX": "Thermax Ltd", "DELHIVERY": "Delhivery Ltd", "HFCL": "HFCL Ltd",
    "FORTIS": "Fortis Healthcare Ltd",
}

_NSE_TO_YAHOO = {"MM": "M&M", "BAJAJ-AUTO": "BAJAJ-AUTO"}

def _yahoo_sym(symbol, exchange="NSE"):
    s = _NSE_TO_YAHOO.get(symbol, symbol)
    if s.endswith(".NS") or s.endswith(".BO") or s.startswith("^"):
        return s
    return f"{s}.BO" if exchange == "BSE" else f"{s}.NS"

# ─── Yahoo Finance Chart API (v8) — direct HTTP ───────────────────────────────

def _yf_chart(yahoo_sym, range_="1y", interval="1d"):
    """
    Direct call to Yahoo Finance v8 chart API.
    Returns list of OHLCV dicts or [].
    range_: 1d 5d 1mo 3mo 6mo 1y 2y 5y max
    interval: 1m 5m 15m 30m 60m 1d 1wk 1mo
    """
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_sym}"
    params = {
        "range": range_,
        "interval": interval,
        "includePrePost": "false",
        "events": "div,splits",
    }
    data = _yf_get(url, params=params)
    if not data:
        # Try query2
        url2 = url.replace("query1", "query2")
        data = _yf_get(url2, params=params)
    if not data:
        return []

    try:
        result = data["chart"]["result"]
        if not result:
            return []
        r = result[0]
        timestamps = r.get("timestamp", [])
        q = r["indicators"]["quote"][0]
        opens   = q.get("open",   [])
        highs   = q.get("high",   [])
        lows    = q.get("low",    [])
        closes  = q.get("close",  [])
        volumes = q.get("volume", [])

        out = []
        for i, ts in enumerate(timestamps):
            c = closes[i] if i < len(closes) else None
            if c is None:
                continue
            out.append({
                "date":   datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S"),
                "open":   round(float(opens[i]   or c), 2),
                "high":   round(float(highs[i]   or c), 2),
                "low":    round(float(lows[i]    or c), 2),
                "close":  round(float(c), 2),
                "volume": int(volumes[i] or 0) if i < len(volumes) else 0,
            })
        return out
    except Exception:
        return []

# ─── Yahoo Finance Quotesummary (fundamentals) ────────────────────────────────

def _yf_quotesummary(yahoo_sym):
    """Direct Yahoo Finance quoteSummary API call"""
    url = f"https://query1.finance.yahoo.com/v11/finance/quoteSummary/{yahoo_sym}"
    modules = "financialData,defaultKeyStatistics,summaryDetail,assetProfile,incomeStatementHistory,balanceSheetHistory"
    params = {"modules": modules, "crumb": ""}
    data = _yf_get(url, params=params)
    if not data:
        url2 = url.replace("query1", "query2")
        data = _yf_get(url2, params=params)
    return data

# ─── nsetools quote ───────────────────────────────────────────────────────────

def _nsetools_quote(symbol):
    key = f"nse:{symbol}"
    hit = _cache.get(key)
    if hit:
        return hit
    try:
        nse = _get_nse()
        if not nse:
            return None
        raw = nse.get_quote(symbol.lower())
        if not raw:
            return None

        curr = float(raw.get("lastPrice") or raw.get("ltp") or 0)
        prev = float(raw.get("previousClose") or raw.get("previousPrice") or curr)
        hl   = raw.get("intraDayHighLow") or {}
        wk   = raw.get("weekHighLow") or {}

        if not curr:
            return None

        chg     = round(curr - prev, 2)
        chg_pct = round((chg / prev * 100) if prev else 0, 2)
        sector  = STOCK_SECTOR.get(symbol.upper(), "N/A")

        result = {
            "symbol":         symbol.upper(),
            "company_name":   INDIAN_STOCKS.get(symbol.upper(), raw.get("companyName", symbol.upper())),
            "current_price":  round(curr, 2),
            "previous_close": round(prev, 2),
            "change":         chg,
            "change_percent": chg_pct,
            "open":   round(float(raw.get("open") or 0), 2),
            "high":   round(float(hl.get("max") or raw.get("dayHigh") or 0), 2),
            "low":    round(float(hl.get("min") or raw.get("dayLow") or 0), 2),
            "volume": int(raw.get("totalTradedVolume") or 0),
            "avg_volume": 0,
            "week_52_high": round(float(wk.get("max") or raw.get("high52") or 0), 2),
            "week_52_low":  round(float(wk.get("min") or raw.get("low52") or 0), 2),
            "market_cap": 0,
            "pe_ratio":   0,
            "sector":   sector,
            "exchange": "NSE",
            "source":   "nsetools",
            "timestamp": datetime.utcnow().isoformat(),
        }
        _cache.set(key, result, ttl=30)
        return result
    except Exception:
        return None

# ─── Yahoo Finance fast quote ─────────────────────────────────────────────────

def _yf_quote_direct(symbol, exchange="NSE"):
    key = f"yf:{symbol}:{exchange}"
    hit = _cache.get(key)
    if hit:
        return hit
    try:
        ysym = _yahoo_sym(symbol, exchange)
        url  = f"https://query1.finance.yahoo.com/v8/finance/chart/{ysym}"
        params = {"range": "2d", "interval": "1d"}
        data = _yf_get(url, params=params)
        if not data:
            url2 = url.replace("query1", "query2")
            data = _yf_get(url2, params=params)
        if not data:
            return None

        r = data["chart"]["result"][0]
        meta = r.get("meta", {})
        curr = float(meta.get("regularMarketPrice") or meta.get("previousClose") or 0)
        prev = float(meta.get("chartPreviousClose") or meta.get("previousClose") or 0)
        if not curr:
            return None

        chg     = round(curr - prev, 2)
        chg_pct = round((chg / prev * 100) if prev else 0, 2)
        sector  = STOCK_SECTOR.get(symbol.upper(), "N/A")

        result = {
            "symbol":         symbol.upper(),
            "yahoo_symbol":   ysym,
            "company_name":   meta.get("longName") or meta.get("shortName") or INDIAN_STOCKS.get(symbol.upper(), symbol),
            "current_price":  round(curr, 2),
            "previous_close": round(prev, 2),
            "change":         chg,
            "change_percent": chg_pct,
            "open":   round(float(meta.get("regularMarketOpen") or curr), 2),
            "high":   round(float(meta.get("regularMarketDayHigh") or curr), 2),
            "low":    round(float(meta.get("regularMarketDayLow") or curr), 2),
            "volume": int(meta.get("regularMarketVolume") or 0),
            "avg_volume": int(meta.get("averageDailyVolume3Month") or 0),
            "week_52_high": round(float(meta.get("fiftyTwoWeekHigh") or 0), 2),
            "week_52_low":  round(float(meta.get("fiftyTwoWeekLow") or 0), 2),
            "market_cap": 0,
            "pe_ratio":   0,
            "sector":   sector,
            "exchange": exchange,
            "source":   "yfinance_direct",
            "timestamp": datetime.utcnow().isoformat(),
        }
        _cache.set(key, result, ttl=45)
        return result
    except Exception:
        return None

# ─── Public: get_stock_quote ──────────────────────────────────────────────────

def get_stock_quote(symbol, exchange="NSE"):
    symbol = symbol.upper().strip()
    if exchange == "NSE":
        q = _nsetools_quote(symbol)
        if q and q["current_price"] > 0:
            return q
    q = _yf_quote_direct(symbol, exchange)
    if q:
        return q
    return {
        "symbol": symbol, "company_name": INDIAN_STOCKS.get(symbol, symbol),
        "current_price": 0, "previous_close": 0, "change": 0, "change_percent": 0,
        "open": 0, "high": 0, "low": 0, "volume": 0, "avg_volume": 0,
        "week_52_high": 0, "week_52_low": 0, "market_cap": 0, "pe_ratio": 0,
        "sector": STOCK_SECTOR.get(symbol, "N/A"), "exchange": exchange,
        "source": "unavailable", "timestamp": datetime.utcnow().isoformat(),
    }

# ─── Public: get_historical_data ──────────────────────────────────────────────

PERIOD_MAP = {
    "1mo": "1mo", "3mo": "3mo", "6mo": "6mo",
    "1y": "1y", "2y": "2y", "5y": "5y", "max": "max",
    "1d": "1d", "5d": "5d",
}

def get_historical_data(symbol, period="1y", interval="1d", exchange="NSE"):
    key = f"hist:{symbol}:{period}:{interval}"
    hit = _cache.get(key)
    if hit is not None:
        return hit

    yf_range    = PERIOD_MAP.get(period, "1y")
    yf_interval = interval if interval in ("1d","1wk","1mo","1h","5m","15m") else "1d"
    ysym        = _yahoo_sym(symbol, exchange)

    data = _yf_chart(ysym, range_=yf_range, interval=yf_interval)

    if not data:
        # Try .BO if .NS failed
        alt = ysym.replace(".NS", ".BO") if ysym.endswith(".NS") else ysym.replace(".BO", ".NS")
        data = _yf_chart(alt, range_=yf_range, interval=yf_interval)

    ttl = 3600 if interval in ("1d", "1wk", "1mo") else 300
    _cache.set(key, data, ttl=ttl)
    return data

# ─── Public: get_fundamentals ─────────────────────────────────────────────────

def get_fundamentals(symbol, exchange="NSE"):
    key = f"fund:{symbol}"
    hit = _cache.get(key)
    if hit:
        return hit

    ysym = _yahoo_sym(symbol, exchange)
    data = _yf_quotesummary(ysym)

    company_name = INDIAN_STOCKS.get(symbol.upper(), symbol)
    sector       = STOCK_SECTOR.get(symbol.upper(), "N/A")
    result = {
        "company_name": company_name, "sector": sector, "industry": "N/A",
        "description": "", "employees": None, "website": "",
        "pe_ratio": 0, "forward_pe": 0, "pb_ratio": 0, "ps_ratio": 0,
        "market_cap": 0, "enterprise_value": 0, "revenue": 0,
        "net_income": 0, "ebitda": 0, "debt_to_equity": 0, "current_ratio": 0,
        "roe": 0, "roa": 0, "profit_margin": 0, "revenue_growth": 0,
        "earnings_growth": 0, "dividend_yield": 0, "dividend_rate": 0,
        "beta": 0, "shares_outstanding": 0, "book_value": 0, "eps": 0,
    }

    if not data:
        _cache.set(key, result, ttl=300)
        return result

    try:
        qsr = data.get("quoteSummary", {}).get("result", [{}])
        if not qsr:
            _cache.set(key, result, ttl=300)
            return result
        r = qsr[0]

        def s(module, field, mul=1):
            try:
                v = r.get(module, {}).get(field, {})
                if isinstance(v, dict):
                    v = v.get("raw", 0)
                return round(float(v or 0) * mul, 4)
            except Exception:
                return 0

        ap = r.get("assetProfile", {})
        fd = r.get("financialData", {})
        ks = r.get("defaultKeyStatistics", {})
        sd = r.get("summaryDetail", {})

        industry = ap.get("industry", "N/A")
        sector_yf = ap.get("sector", "N/A")
        clean_sector = _get_sector(industry, sector_yf)
        if clean_sector == "N/A":
            clean_sector = STOCK_SECTOR.get(symbol.upper(), "N/A")

        result.update({
            "company_name":    ap.get("longName") or ap.get("longBusinessSummary", "")[:30] or company_name,
            "sector":          clean_sector,
            "industry":        industry,
            "description":     ap.get("longBusinessSummary", "")[:600],
            "employees":       ap.get("fullTimeEmployees"),
            "website":         ap.get("website", ""),
            "pe_ratio":        s("summaryDetail", "trailingPE"),
            "forward_pe":      s("summaryDetail", "forwardPE"),
            "pb_ratio":        s("defaultKeyStatistics", "priceToBook"),
            "ps_ratio":        s("summaryDetail", "priceToSalesTrailing12Months"),
            "market_cap":      s("summaryDetail", "marketCap"),
            "enterprise_value": s("defaultKeyStatistics", "enterpriseValue"),
            "revenue":         s("financialData", "totalRevenue"),
            "net_income":      s("financialData", "netIncomeToCommon"),
            "ebitda":          s("financialData", "ebitda"),
            "debt_to_equity":  s("financialData", "debtToEquity"),
            "current_ratio":   s("financialData", "currentRatio"),
            "roe":             s("financialData", "returnOnEquity", 100),
            "roa":             s("financialData", "returnOnAssets", 100),
            "profit_margin":   s("financialData", "profitMargins", 100),
            "revenue_growth":  s("financialData", "revenueGrowth", 100),
            "earnings_growth": s("financialData", "earningsGrowth", 100),
            "dividend_yield":  s("summaryDetail", "dividendYield", 100),
            "dividend_rate":   s("summaryDetail", "dividendRate"),
            "beta":            s("summaryDetail", "beta"),
            "shares_outstanding": s("defaultKeyStatistics", "sharesOutstanding"),
            "book_value":      s("defaultKeyStatistics", "bookValue"),
            "eps":             s("defaultKeyStatistics", "trailingEps"),
        })
    except Exception:
        pass

    _cache.set(key, result, ttl=3600)
    return result

# ─── Public: search_stocks ────────────────────────────────────────────────────

def search_stocks(query):
    q_up = query.upper().strip()
    q_lo = query.lower().strip()
    out  = []
    for sym, name in INDIAN_STOCKS.items():
        score = 0
        if sym == q_up:                     score = 100
        elif sym.startswith(q_up):          score = 80
        elif q_up in sym:                   score = 60
        elif name.upper().startswith(q_up): score = 70
        elif q_lo in name.lower():          score = 40
        if score:
            out.append({"symbol": sym, "company_name": name,
                        "exchange": "NSE", "yahoo_symbol": f"{sym}.NS", "_s": score})
    out.sort(key=lambda x: x["_s"], reverse=True)
    for r in out: del r["_s"]
    return out[:25]

# ─── Public: get_market_indices ───────────────────────────────────────────────

def get_market_indices():
    key = "indices"
    hit = _cache.get(key)
    if hit:
        return hit

    result = {}
    nse = _get_nse()

    # Try nsetools for Nifty50 and BankNifty
    if nse:
        for label, nse_name in [("NIFTY50", "nifty 50"), ("BANKNIFTY", "nifty bank")]:
            try:
                q = nse.get_index_quote(nse_name)
                if q:
                    curr    = float(q.get("lastPrice") or 0)
                    chg     = float(q.get("change") or 0)
                    chg_pct = float(q.get("pChange") or 0)
                    if curr:
                        result[label] = {
                            "symbol": label, "current": round(curr, 2),
                            "change": round(chg, 2), "change_percent": round(chg_pct, 2),
                            "prev_close": round(curr - chg, 2),
                        }
            except Exception:
                pass

    # Direct Yahoo Finance chart API for all indices
    yf_map = {
        "NIFTY50":   "^NSEI",
        "SENSEX":    "^BSESN",
        "BANKNIFTY": "^NSEBANK",
        "NIFTYIT":   "^CNXIT",
    }
    for label, ysym in yf_map.items():
        if label in result:
            continue
        try:
            data = _yf_get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{ysym}",
                params={"range": "2d", "interval": "1d"}
            )
            if data:
                meta = data["chart"]["result"][0]["meta"]
                curr = float(meta.get("regularMarketPrice") or meta.get("previousClose") or 0)
                prev = float(meta.get("chartPreviousClose") or meta.get("previousClose") or 0)
                if curr:
                    chg     = round(curr - prev, 2)
                    chg_pct = round((chg / prev * 100) if prev else 0, 2)
                    result[label] = {
                        "symbol": label, "current": round(curr, 2),
                        "change": chg, "change_percent": chg_pct,
                        "prev_close": round(prev, 2),
                    }
        except Exception:
            pass

    # Ensure all keys exist
    for label in ["NIFTY50", "SENSEX", "BANKNIFTY", "NIFTYIT"]:
        if label not in result:
            result[label] = {"symbol": label, "current": 0, "change": 0,
                             "change_percent": 0, "prev_close": 0}

    _cache.set(key, result, ttl=60)
    return result

# ─── Public: get_top_gainers_losers ──────────────────────────────────────────

def get_top_gainers_losers():
    key = "movers"
    hit = _cache.get(key)
    if hit:
        return hit

    nse = _get_nse()
    if nse:
        try:
            def _fmt(lst):
                out = []
                for s in (lst or [])[:6]:
                    sym = str(s.get("symbol", "")).upper()
                    if not sym: continue
                    out.append({
                        "symbol": sym,
                        "company_name": INDIAN_STOCKS.get(sym, sym),
                        "price": round(float(s.get("ltp") or s.get("lastPrice") or 0), 2),
                        "change_percent": round(float(s.get("perChange") or s.get("pChange") or 0), 2),
                        "change": round(float(s.get("net_price") or s.get("change") or 0), 2),
                    })
                return out
            result = {
                "gainers": _fmt(nse.get_top_gainers()),
                "losers":  _fmt(nse.get_top_losers()),
            }
            _cache.set(key, result, ttl=120)
            return result
        except Exception:
            pass

    # Fallback via direct YF chart API for sample stocks
    SAMPLE = ["RELIANCE","TCS","HDFCBANK","INFY","ICICIBANK",
              "SBIN","BHARTIARTL","HINDUNILVR","ITC","LT",
              "WIPRO","AXISBANK","KOTAKBANK","SUNPHARMA","TITAN"]
    stocks = []
    for sym in SAMPLE:
        try:
            data = _yf_get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}.NS",
                params={"range": "2d", "interval": "1d"}
            )
            if data:
                meta = data["chart"]["result"][0]["meta"]
                curr = float(meta.get("regularMarketPrice") or 0)
                prev = float(meta.get("chartPreviousClose") or 0)
                if curr and prev:
                    pct = (curr - prev) / prev * 100
                    stocks.append({
                        "symbol": sym, "company_name": INDIAN_STOCKS.get(sym, sym),
                        "price": round(curr, 2), "change_percent": round(pct, 2),
                        "change": round(curr - prev, 2),
                    })
        except Exception:
            continue

    stocks.sort(key=lambda x: x["change_percent"], reverse=True)
    result = {"gainers": stocks[:5], "losers": list(reversed(stocks[-5:]))}
    _cache.set(key, result, ttl=120)
    return result

# ─── Public: get_sector_performance ──────────────────────────────────────────

def get_sector_performance():
    key = "sectors"
    hit = _cache.get(key)
    if hit:
        return hit

    sectors = {
        "IT":      ["TCS", "INFY", "WIPRO"],
        "Banking": ["HDFCBANK", "ICICIBANK", "SBIN"],
        "Pharma":  ["SUNPHARMA", "DRREDDY", "CIPLA"],
        "Auto":    ["MARUTI", "TATAMOTORS", "HEROMOTOCO"],
        "Energy":  ["RELIANCE", "ONGC", "BPCL"],
        "FMCG":    ["HINDUNILVR", "ITC", "NESTLEIND"],
    }
    result = {}
    for sector, stocks in sectors.items():
        changes = []
        for sym in stocks:
            q = _nsetools_quote(sym) or _yf_quote_direct(sym)
            if q and q.get("change_percent") is not None:
                changes.append(q["change_percent"])
        result[sector] = round(sum(changes) / len(changes), 2) if changes else 0.0

    _cache.set(key, result, ttl=180)
    return result

# ─── Public: get_batch_quotes ─────────────────────────────────────────────────

def get_batch_quotes(symbols):
    res = {}
    for sym in symbols[:20]:
        res[sym] = get_stock_quote(sym)
        time.sleep(0.02)
    return res
