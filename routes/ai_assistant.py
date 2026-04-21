"""
AI Assistant - BullsEye
Primary: Groq (Llama 3.3-70B) - fast, free, excellent
Fallback: Google Gemini 1.5 Flash
"""
import uuid
import json
import os
import requests
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from database import db
from models.user import User, AIConversation, Portfolio, Holding
from services.stock_service import get_stock_quote, get_fundamentals, STOCK_SECTOR

ai_bp = Blueprint("ai", __name__)

# ─── Hardcoded API Keys (also reads from env) ─────────────────────────────────
GROQ_API_KEY   = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ─── System prompt ────────────────────────────────────────────────────────────

SYSTEM_PROMPT_TEMPLATE = """You are BullsEye AI, an expert financial analyst for the Indian stock market (NSE/BSE).

{risk_context}

Your knowledge covers:
- All major Indian stocks: Nifty 50, Nifty Next 50, midcap, smallcap
- Fundamental analysis: P/E, P/B, ROE, ROCE, debt levels, margins, cash flows
- Technical analysis: RSI, MACD, moving averages, support/resistance, volume
- Sector analysis: IT, Banking, FMCG, Pharma, Auto, Energy, Metals, Real Estate
- Portfolio strategy: diversification, rebalancing, risk management
- Indian regulations: SEBI, LTCG (12.5% above ₹1.25L), STCG (20%), STT
- Mutual funds, ETFs, index funds, SIP strategies
- IPO analysis, FII/DII data, RBI policy impact
- Economic indicators: GDP, inflation, IIP, PMI

CRITICAL RULES:
1. ALWAYS tailor advice to the user's risk profile stated above
2. Give specific, detailed answers — never generic responses
3. When asked about a stock, analyze that specific stock with real fundamentals
4. Use ₹ for all Indian Rupee values
5. Give ACTIONABLE insights
6. Always end with: "⚠️ Educational content only. Not SEBI-registered advice."
7. For {risk_label} investors: {risk_instruction}"""

RISK_CONTEXTS = {
    'conservative': {
        'context': """🛡️ USER RISK PROFILE: CONSERVATIVE
This investor prioritizes capital preservation over high returns. They have low risk tolerance and prefer:
- Large-cap, dividend-paying stocks (Nifty 50 bluechips)
- Stable sectors: FMCG, IT services, pharma majors, utilities
- Debt-to-equity < 0.5, consistent dividend history
- P/E ratio reasonable vs sector (not stretched valuations)
- Avoid: small-caps, high-beta stocks, cyclicals, highly leveraged companies""",
        'label': 'Conservative',
        'instruction': 'Recommend only low-risk large-cap stocks with strong fundamentals. Flag any high-risk suggestions prominently. Focus on capital protection, not speculation.'
    },
    'moderate': {
        'context': """⚖️ USER RISK PROFILE: MODERATE
This investor seeks balanced risk-reward. They can accept moderate volatility for better returns:
- Mix of large-cap (60%) and mid-cap (40%) stocks
- Quality growth stocks with reasonable valuations
- P/E can be above average if earnings growth justifies it
- Comfortable with 1-3 year investment horizon
- Avoid: highly speculative stocks, heavy leverage plays""",
        'label': 'Moderate',
        'instruction': 'Balance growth and safety in recommendations. Suggest a mix of stable large-caps and quality growth mid-caps. Flag stocks with extreme risk or valuation.'
    },
    'aggressive': {
        'context': """🚀 USER RISK PROFILE: AGGRESSIVE
This investor seeks maximum returns and can handle significant volatility:
- Open to small-caps, mid-caps, and growth stocks
- Sectoral themes and momentum plays are acceptable
- Can accept short-term volatility for long-term gains
- Comfortable with 3-5+ year horizon for wealth multiplication
- Considers turnaround stories and emerging sector leaders""",
        'label': 'Aggressive',
        'instruction': 'Can suggest high-growth, high-beta stocks. Include small/mid-cap gems if fundamentals support it. Still mention risks clearly but do not shy away from growth recommendations.'
    }
}

def get_system_prompt(risk_profile='moderate'):
    rc = RISK_CONTEXTS.get(risk_profile, RISK_CONTEXTS['moderate'])
    return SYSTEM_PROMPT_TEMPLATE.format(
        risk_context=rc['context'],
        risk_label=rc['label'],
        risk_instruction=rc['instruction']
    )

# ─── API callers ──────────────────────────────────────────────────────────────

def call_groq(messages, system_prompt):
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "system", "content": system_prompt}] + messages,
        "max_tokens": 2000,
        "temperature": 0.7,
        "stream": False,
    }
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers=headers, json=payload, timeout=30
    )
    if r.status_code == 200:
        return r.json()["choices"][0]["message"]["content"]
    raise Exception(f"Groq {r.status_code}: {r.text[:300]}")


def call_gemini(messages, system_prompt):
    contents = []
    for msg in messages:
        role = "user" if msg["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": msg["content"]}]})
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": contents,
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {"maxOutputTokens": 2000, "temperature": 0.7},
    }
    r = requests.post(url, json=payload, timeout=30)
    if r.status_code == 200:
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    raise Exception(f"Gemini {r.status_code}: {r.text[:200]}")


def get_ai_response(messages, risk_profile='moderate'):
    """Try Groq first, then Gemini"""
    system_prompt = get_system_prompt(risk_profile)
    last_err = None
    if GROQ_API_KEY:
        try:
            return call_groq(messages, system_prompt)
        except Exception as e:
            last_err = e
    if GEMINI_API_KEY:
        try:
            return call_gemini(messages, system_prompt)
        except Exception as e:
            last_err = e
    return f"⚠️ AI service temporarily unavailable. Error: {str(last_err)[:100]}\n\nPlease try again in a moment."

# ─── Routes ───────────────────────────────────────────────────────────────────

@ai_bp.route("/chat", methods=["POST"])
@jwt_required()
def chat():
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    if user and user.is_guest:
        return jsonify({"error": "AI Assistant requires registration. Please sign up — it's free!"}), 403

    data       = request.get_json() or {}
    message    = data.get("message", "").strip()
    session_id = data.get("session_id", str(uuid.uuid4()))

    if not message:
        return jsonify({"error": "Message required"}), 400

    # Load conversation history (last 20 messages = 10 exchanges)
    history = AIConversation.query.filter_by(
        user_id=user_id, session_id=session_id
    ).order_by(AIConversation.created_at.asc()).limit(20).all()

    messages = [{"role": h.role, "content": h.content} for h in history]
    messages.append({"role": "user", "content": message})

    risk_profile = user.risk_profile if user else 'moderate'
    ai_response = get_ai_response(messages, risk_profile)

    # Save conversation
    db.session.add(AIConversation(user_id=user_id, session_id=session_id, role="user",      content=message))
    db.session.add(AIConversation(user_id=user_id, session_id=session_id, role="assistant", content=ai_response))
    db.session.commit()

    return jsonify({"response": ai_response, "session_id": session_id}), 200


@ai_bp.route("/analyze-stock/<symbol>", methods=["GET"])
@jwt_required()
def analyze_stock(symbol):
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    if user and user.is_guest:
        return jsonify({"error": "Not available for guests"}), 403

    fund  = get_fundamentals(symbol)
    quote = get_stock_quote(symbol)
    sector = STOCK_SECTOR.get(symbol.upper(), fund.get("sector", "N/A"))

    # Build a rich, specific prompt
    prompt = f"""Provide a comprehensive investment analysis of {symbol} ({fund.get('company_name', symbol)}) for an Indian retail investor.

═══ LIVE MARKET DATA ═══
• Current Price: ₹{quote.get('current_price', 'N/A')}
• Today's Change: {quote.get('change_percent', 0):+.2f}% (₹{quote.get('change', 0):+.2f})
• 52-Week Range: ₹{quote.get('week_52_low', 'N/A')} – ₹{quote.get('week_52_high', 'N/A')}
• Open/High/Low: ₹{quote.get('open', 'N/A')} / ₹{quote.get('high', 'N/A')} / ₹{quote.get('low', 'N/A')}
• Volume: {quote.get('volume', 'N/A'):,}

═══ FUNDAMENTAL DATA ═══
• Sector: {sector} | Industry: {fund.get('industry', 'N/A')}
• P/E Ratio: {fund.get('pe_ratio', 'N/A')} | Forward P/E: {fund.get('forward_pe', 'N/A')}
• P/B Ratio: {fund.get('pb_ratio', 'N/A')} | P/S Ratio: {fund.get('ps_ratio', 'N/A')}
• Market Cap: ₹{fund.get('market_cap', 0):,.0f}
• Revenue: ₹{fund.get('revenue', 0):,.0f} | Net Income: ₹{fund.get('net_income', 0):,.0f}
• EBITDA: ₹{fund.get('ebitda', 0):,.0f}
• ROE: {fund.get('roe', 'N/A')}% | ROA: {fund.get('roa', 'N/A')}%
• Profit Margin: {fund.get('profit_margin', 'N/A')}%
• Revenue Growth: {fund.get('revenue_growth', 'N/A')}% | Earnings Growth: {fund.get('earnings_growth', 'N/A')}%
• Debt/Equity: {fund.get('debt_to_equity', 'N/A')} | Current Ratio: {fund.get('current_ratio', 'N/A')}
• EPS: ₹{fund.get('eps', 'N/A')} | Book Value: ₹{fund.get('book_value', 'N/A')}
• Dividend Yield: {fund.get('dividend_yield', 'N/A')}% | Beta: {fund.get('beta', 'N/A')}

═══ COMPANY DESCRIPTION ═══
{fund.get('description', 'N/A')[:300]}

Please provide:
1. **📊 Overall Verdict** — Strong Buy / Buy / Hold / Sell / Strong Sell with clear reasoning
2. **💪 Key Strengths** (3-4 specific bullet points based on actual data)
3. **⚠️ Key Risks** (3-4 specific concerns)
4. **💰 Valuation Assessment** — Compare P/E to {sector} sector average. Is it over/under/fairly valued?
5. **📈 Price Analysis** — Is current price near 52W high/low? What does that mean?
6. **🎯 Suitable For** — Which investor profile? (long-term wealth builder / income investor / trader)
7. **📋 Key Metrics to Watch** — 2-3 metrics investors should track for this stock"""

    messages = [{"role": "user", "content": prompt}]
    analysis = get_ai_response(messages, user.risk_profile if user else 'moderate')

    return jsonify({
        "symbol": symbol, "analysis": analysis,
        "fundamentals": fund, "quote": quote
    }), 200


@ai_bp.route("/analyze-portfolio/<int:portfolio_id>", methods=["GET"])
@jwt_required()
def analyze_portfolio(portfolio_id):
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    if user and user.is_guest:
        return jsonify({"error": "Not available for guests"}), 403

    portfolio = Portfolio.query.filter_by(id=portfolio_id, user_id=user_id).first()
    if not portfolio:
        return jsonify({"error": "Portfolio not found"}), 404
    if not portfolio.holdings:
        return jsonify({"error": "Portfolio is empty — add some holdings first"}), 400

    # Build comprehensive portfolio data
    holdings_info = []
    total_invested = total_current = 0.0
    sector_map = {}

    for h in portfolio.holdings:
        q          = get_stock_quote(h.symbol)
        cp         = q.get("current_price", h.avg_buy_price) or h.avg_buy_price
        invested   = h.quantity * h.avg_buy_price
        current    = h.quantity * cp
        pnl        = current - invested
        pnl_pct    = (pnl / invested * 100) if invested else 0
        sector     = STOCK_SECTOR.get(h.symbol.upper(), q.get("sector", "Unknown"))
        total_invested += invested
        total_current  += current
        sector_map[sector] = sector_map.get(sector, 0) + current

        holdings_info.append({
            "symbol":    h.symbol,
            "name":      h.company_name or h.symbol,
            "sector":    sector,
            "qty":       h.quantity,
            "avg_price": h.avg_buy_price,
            "curr_price": cp,
            "invested":  invested,
            "current":   current,
            "pnl":       round(pnl, 2),
            "pnl_pct":   round(pnl_pct, 2),
            "weight":    0,
        })

    # Calculate weights
    if total_current > 0:
        for h in holdings_info:
            h["weight"] = round(h["current"] / total_current * 100, 2)
        for s in sector_map:
            sector_map[s] = round(sector_map[s] / total_current * 100, 2)

    total_pnl     = total_current - total_invested
    total_pnl_pct = (total_pnl / total_invested * 100) if total_invested else 0

    # Sort by weight for display
    holdings_info.sort(key=lambda x: x["weight"], reverse=True)

    # Build rich holdings string
    holdings_str = "\n".join([
        f"  • {h['symbol']} ({h['name'][:25]}) | Sector: {h['sector']} | "
        f"Weight: {h['weight']}% | Qty: {h['qty']} | Avg: ₹{h['avg_price']:.0f} → "
        f"Now: ₹{h['curr_price']:.0f} | P&L: {h['pnl_pct']:+.1f}% (₹{h['pnl']:+,.0f})"
        for h in holdings_info
    ])

    sector_str = " | ".join([f"{s}: {v}%" for s, v in sorted(sector_map.items(), key=lambda x: x[1], reverse=True)])

    prompt = f"""Perform a comprehensive portfolio analysis for an Indian retail investor:

═══ PORTFOLIO OVERVIEW ═══
• Total Holdings: {len(holdings_info)} stocks
• Total Invested: ₹{total_invested:,.0f}
• Current Value: ₹{total_current:,.0f}
• Overall P&L: {total_pnl_pct:+.2f}% (₹{total_pnl:+,.0f})

═══ HOLDINGS (sorted by weight) ═══
{holdings_str}

═══ SECTOR ALLOCATION ═══
{sector_str}

Please provide a detailed portfolio review covering:

1. **📊 Portfolio Health Score** — Rate 0-100 with specific reasoning (consider: diversification, sector balance, stock quality, P&L performance)

2. **💪 Top 3 Strengths** of this portfolio (be specific about which stocks/sectors are working well)

3. **⚠️ Top 3 Risks** (identify concentration risk, underperforming stocks, missing sectors, or overvaluation concerns)

4. **🏭 Sector Analysis**
   - Which sectors are overweight/underweight vs ideal Indian equity portfolio?
   - Key sectors missing from this portfolio
   - Current sector performance context in Indian markets

5. **📈 Stock-by-Stock Assessment**
   - Best performer: Why it's doing well, should they hold/add more?
   - Worst performer: Is this temporary or structural? Hold, average down, or exit?
   - Any stock that looks concerning vs others in same sector?

6. **🔧 3 Actionable Improvements**
   - Specific actions to take (e.g., "Reduce RELIANCE weight from 61% to 25%")
   - Include timing (immediately, next quarter, on dips)

7. **➕ Recommended Additions** — Suggest 3 specific NSE stocks to add for better diversification, with brief reasoning for each

8. **💰 Rebalancing Suggestion** — If portfolio is concentrated, suggest target weights for each holding"""

    messages = [{"role": "user", "content": prompt}]
    analysis = get_ai_response(messages, user.risk_profile if user else 'moderate')

    return jsonify({
        "analysis": analysis,
        "summary": {
            "total_invested": round(total_invested, 2),
            "total_current":  round(total_current, 2),
            "total_pnl":      round(total_pnl, 2),
            "total_pnl_pct":  round(total_pnl_pct, 2),
            "num_holdings":   len(holdings_info),
        },
        "holdings":        holdings_info,
        "sector_breakdown": sector_map,
    }), 200


@ai_bp.route("/history", methods=["GET"])
@jwt_required()
def get_history():
    user_id    = int(get_jwt_identity())
    session_id = request.args.get("session_id")
    query = AIConversation.query.filter_by(user_id=user_id)
    if session_id:
        query = query.filter_by(session_id=session_id)
    convs = query.order_by(AIConversation.created_at.asc()).limit(50).all()
    return jsonify({"conversations": [c.to_dict() for c in convs]}), 200
