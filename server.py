"""
FastAPI server for Financial Assistant Dashboard.
Serves the real-time dashboard and API endpoints.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import os

import database as db

logger = logging.getLogger(__name__)
from contextlib import asynccontextmanager
from telegram import Update

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    webhook_url = os.getenv("WEBHOOK_URL")
    if webhook_url:
        bot_app = app.state.bot_app
        await bot_app.initialize()
        await bot_app.start()
        # Set webhook URL (must be HTTPS)
        webhook_endpoint = f"{webhook_url.rstrip('/')}/webhook"
        await bot_app.bot.set_webhook(url=webhook_endpoint)
        logger.info(f"✅ Webhook set to {webhook_endpoint}")
    yield
    # Shutdown
    if webhook_url:
        bot_app = app.state.bot_app
        await bot_app.bot.delete_webhook()
        await bot_app.stop()
        await bot_app.shutdown()
        logger.info("❌ Webhook stopped.")

app = FastAPI(title="Financial Assistant Dashboard", version="1.0.0", lifespan=lifespan)

# Serve static files
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.post("/webhook")
async def telegram_webhook(request: Request):
    """Receive incoming webhook updates from Telegram."""
    bot_app = app.state.bot_app
    data = await request.json()
    update = Update.de_json(data, bot_app.bot)
    await bot_app.process_update(update)
    return {"ok": True}


# ── SSE Event System ──
sse_clients: list[asyncio.Queue] = []


async def sse_notify(data: dict):
    """Push an event to all connected SSE clients."""
    message = json.dumps(data, default=str)
    disconnected = []

    for i, queue in enumerate(sse_clients):
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            disconnected.append(i)

    # Clean up disconnected clients
    for i in reversed(disconnected):
        sse_clients.pop(i)


# ══════════════════════════════════════════════
# Pages
# ══════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def dashboard_page():
    """Serve the dashboard HTML page."""
    html_path = os.path.join(STATIC_DIR, "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


# ══════════════════════════════════════════════
# API Endpoints
# ══════════════════════════════════════════════

@app.get("/api/summary")
async def api_summary(days: int = Query(30, ge=1, le=365)):
    """Get financial summary."""
    user_ids = await db.get_all_user_ids()
    if not user_ids:
        return {
            "total_income": 0,
            "total_expense": 0,
            "balance": 0,
            "savings_rate": 0,
            "transaction_count": 0,
            "period_days": days,
        }

    # Aggregate across all users (single-user app in practice)
    combined = {
        "total_income": 0,
        "total_expense": 0,
        "balance": 0,
        "savings_rate": 0,
        "transaction_count": 0,
        "period_days": days,
    }
    for uid in user_ids:
        summary = await db.get_summary(uid, days=days)
        combined["total_income"] += summary["total_income"]
        combined["total_expense"] += summary["total_expense"]
        combined["transaction_count"] += summary["transaction_count"]

    combined["balance"] = combined["total_income"] - combined["total_expense"]
    if combined["total_income"] > 0:
        combined["savings_rate"] = round(
            combined["balance"] / combined["total_income"] * 100, 1
        )

    return combined


@app.get("/api/transactions")
async def api_transactions(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    tx_type: Optional[str] = Query(None),
    days: Optional[int] = Query(None, ge=1, le=365),
):
    """Get list of transactions."""
    user_ids = await db.get_all_user_ids()
    all_transactions = []
    for uid in user_ids:
        txs = await db.get_transactions(uid, limit=limit, offset=offset, tx_type=tx_type, days=days)
        all_transactions.extend(txs)

    # Sort by date descending
    all_transactions.sort(key=lambda x: x["created_at"], reverse=True)
    return all_transactions[:limit]


@app.get("/api/daily")
async def api_daily(days: int = Query(30, ge=1, le=90)):
    """Get daily spending/income for chart."""
    user_ids = await db.get_all_user_ids()
    if not user_ids:
        return []

    # Use first user (single-user design)
    uid = user_ids[0] if user_ids else 0
    return await db.get_daily_spending(uid, days=days)


@app.get("/api/categories")
async def api_categories(days: int = Query(30, ge=1, le=365)):
    """Get category breakdown."""
    user_ids = await db.get_all_user_ids()
    if not user_ids:
        return []

    uid = user_ids[0] if user_ids else 0
    return await db.get_category_breakdown(uid, days=days)


@app.get("/api/monthly")
async def api_monthly(months: int = Query(6, ge=1, le=12)):
    """Get monthly income vs expense trend."""
    user_ids = await db.get_all_user_ids()
    if not user_ids:
        return []

    uid = user_ids[0] if user_ids else 0
    return await db.get_monthly_trend(uid, months=months)


@app.get("/api/export")
async def api_export():
    """Download Excel export."""
    user_ids = await db.get_all_user_ids()
    if not user_ids:
        return {"error": "No data to export"}

    uid = user_ids[0]
    filepath = await db.export_to_excel(uid)
    filename = os.path.basename(filepath)

    return FileResponse(
        path=filepath,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ══════════════════════════════════════════════
# Savings Goals API
# ══════════════════════════════════════════════

@app.get("/api/savings")
async def api_savings():
    """Get all savings goals."""
    user_ids = await db.get_all_user_ids()
    if not user_ids:
        return []
    uid = user_ids[0]
    return await db.get_savings_goals(uid)


@app.post("/api/savings")
async def api_create_savings(request: Request):
    """Create a new savings goal from dashboard."""
    body = await request.json()
    user_ids = await db.get_all_user_ids()
    if not user_ids:
        return {"error": "No user found. Send a message to the bot first."}
    uid = user_ids[0]
    goal = await db.add_savings_goal(uid, body["name"], body["target_amount"])
    return goal


# ══════════════════════════════════════════════
# Budget API
# ══════════════════════════════════════════════

@app.get("/api/budgets")
async def api_budgets():
    """Get budget vs actual spending."""
    user_ids = await db.get_all_user_ids()
    if not user_ids:
        return []
    uid = user_ids[0]
    return await db.get_budget_vs_actual(uid)


@app.post("/api/budgets")
async def api_set_budget(request: Request):
    """Set/update a budget from dashboard."""
    body = await request.json()
    user_ids = await db.get_all_user_ids()
    if not user_ids:
        return {"error": "No user found. Send a message to the bot first."}
    uid = user_ids[0]
    result = await db.set_budget(uid, body["category"], body["monthly_limit"])
    return result


# ══════════════════════════════════════════════
# Analysis & Trend API
# ══════════════════════════════════════════════

@app.get("/api/analysis")
async def api_analysis():
    """Get behavior analysis and recommendations."""
    user_ids = await db.get_all_user_ids()
    if not user_ids:
        return {
            "score": 0,
            "total_income": 0,
            "total_expense": 0,
            "daily_average": 0,
            "overall_trend": "stable",
            "overall_change": 0,
            "top_categories": [],
            "recommendations": [],
            "over_budget_count": 0,
        }
    uid = user_ids[0]
    return await db.get_behavior_analysis(uid)


@app.get("/api/trend")
async def api_trend(period: str = Query("daily", pattern="^(daily|monthly|annual)$")):
    """Get trend data for specified period."""
    user_ids = await db.get_all_user_ids()
    if not user_ids:
        return []
    uid = user_ids[0]
    return await db.get_trend_data(uid, period=period)


# ══════════════════════════════════════════════
# Accounts API
# ══════════════════════════════════════════════

@app.get("/api/accounts")
async def api_accounts():
    """Get all bank/e-wallet accounts."""
    user_ids = await db.get_all_user_ids()
    if not user_ids:
        return []
    uid = user_ids[0]
    return await db.get_accounts(uid)


@app.post("/api/accounts")
async def api_save_account(request: Request):
    """Add or update an account balance."""
    body = await request.json()
    user_ids = await db.get_all_user_ids()
    if not user_ids:
        return {"error": "No user found. Send a message to the bot first."}
    uid = user_ids[0]
    acc = await db.add_or_update_account(
        uid, body["name"], float(body["balance"]), body.get("account_type", "bank")
    )
    return acc


# ══════════════════════════════════════════════
# Transaction Management API
# ══════════════════════════════════════════════

@app.put("/api/transactions/{tx_id}")
async def api_edit_transaction(tx_id: int, request: Request):
    """Edit a transaction's amount, description, or type."""
    body = await request.json()
    user_ids = await db.get_all_user_ids()
    if not user_ids:
        return {"error": "No user found."}
    uid = user_ids[0]
    tx = await db.edit_transaction(
        user_id=uid,
        tx_id=tx_id,
        new_amount=body.get("amount"),
        new_description=body.get("description"),
        new_type=body.get("type"),
    )
    if not tx:
        return {"error": "Transaction not found."}
    return tx


@app.delete("/api/transactions/{tx_id}")
async def api_delete_transaction(tx_id: int):
    """Delete a specific transaction by ID."""
    user_ids = await db.get_all_user_ids()
    if not user_ids:
        return {"error": "No user found."}
    uid = user_ids[0]
    tx = await db.delete_transaction_by_id(uid, tx_id)
    if not tx:
        return {"error": "Transaction not found."}
    return {"success": True, "deleted": tx}


# ══════════════════════════════════════════════
# Server-Sent Events (SSE)
# ══════════════════════════════════════════════

@app.get("/sse")
async def sse_endpoint(request: Request):
    """SSE endpoint for real-time dashboard updates."""

    async def event_generator():
        queue = asyncio.Queue(maxsize=50)
        sse_clients.append(queue)

        try:
            # Send initial ping
            yield f"data: {json.dumps({'event': 'connected', 'timestamp': datetime.now().isoformat()})}\n\n"

            while True:
                # Check if client is still connected
                if await request.is_disconnected():
                    break

                try:
                    data = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    # Send heartbeat to keep connection alive
                    yield f"data: {json.dumps({'event': 'heartbeat', 'timestamp': datetime.now().isoformat()})}\n\n"

        except asyncio.CancelledError:
            pass
        finally:
            if queue in sse_clients:
                sse_clients.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
