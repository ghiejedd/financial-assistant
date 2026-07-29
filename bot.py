"""
Telegram Bot for Financial Assistant.
Handles user interactions, parses natural language input,
and records financial transactions.
"""

import re
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.request import HTTPXRequest
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

import database as db

logger = logging.getLogger(__name__)

# ── SSE Event Queue ──
# This will be set by server.py to push real-time events to the dashboard
sse_notify = None


def set_sse_notify(callback):
    """Set the SSE notification callback (called from server.py)."""
    global sse_notify
    sse_notify = callback


def format_rupiah(amount: float) -> str:
    """Format number as Indonesian Rupiah."""
    if amount >= 1_000_000:
        if amount % 1_000_000 == 0:
            return f"Rp {amount / 1_000_000:.0f} jt"
        return f"Rp {amount:,.0f}".replace(",", ".")
    elif amount >= 1_000:
        if amount % 1_000 == 0:
            return f"Rp {amount / 1_000:.0f} rb"
        return f"Rp {amount:,.0f}".replace(",", ".")
    return f"Rp {amount:,.0f}".replace(",", ".")


def parse_amount(text: str) -> float | None:
    """
    Parse Indonesian-style amount from text.
    Supports: 35rb, 35k, 5jt, 5.5jt, 1.500.000, 150000, etc.
    """
    text = text.strip().lower().replace(" ", "")

    # Pattern: number + suffix (rb/ribu/k/jt/juta/m)
    match = re.search(r'(\d+[.,]?\d*)\s*(rb|ribu|k|jt|juta|m)\b', text)
    if match:
        num_str = match.group(1).replace(",", ".")
        num = float(num_str)
        suffix = match.group(2)

        if suffix in ("rb", "ribu", "k"):
            return num * 1_000
        elif suffix in ("jt", "juta"):
            return num * 1_000_000
        elif suffix == "m":
            return num * 1_000_000_000
        return num

    # Pattern: plain number with dots as thousand separator (1.500.000)
    match = re.search(r'(\d{1,3}(?:\.\d{3})+)', text)
    if match:
        return float(match.group(1).replace(".", ""))

    # Pattern: plain number (150000)
    match = re.search(r'(\d{4,})', text)
    if match:
        return float(match.group(1))

    # Pattern: small number (for amounts like 50, 100 — treat as thousands only if >= 5)
    match = re.search(r'(\d+)', text)
    if match:
        num = float(match.group(1))
        if num >= 5:
            return num * 1_000  # assume thousands
        return None

    return None


def detect_type_and_category(description: str, raw_text: str = "") -> tuple[str, str, str]:
    """
    Detect transaction type and category from description.
    Returns (type, category_key, category_display).
    """
    desc_lower = description.lower().strip()
    raw_lower = raw_text.lower().strip()

    # Explicit symbol or prefix checks
    if raw_lower.startswith("+") or raw_lower.startswith("masuk") or raw_lower.startswith("dapat") or raw_lower.startswith("in"):
        is_income = True
    elif raw_lower.startswith("-") or raw_lower.startswith("keluar") or raw_lower.startswith("bayar") or raw_lower.startswith("out"):
        is_income = False
    else:
        income_keywords = [
            "gaji", "salary", "freelance", "project", "proyek",
            "bonus", "thr", "cashback", "reward", "pendapatan",
            "terima", "masuk", "income", "cuan", "jual", "terjual",
            "dapat", "dapet", "diberi", "diberikan", "bunga", "dividen",
            "saham", "untung", "profit", "nambah", "transfer dari", "dpt", "pemasukan"
        ]
        is_income = any(kw in desc_lower or kw in raw_lower for kw in income_keywords)

    cat_key, cat_display = db.auto_categorize(description)

    if is_income:
        tx_type = "income"
        if cat_key not in db.INCOME_CATEGORIES:
            cat_key = "lainnya"
            cat_display = db.INCOME_CATEGORIES.get("lainnya", "📦 Lainnya")
        else:
            cat_display = db.INCOME_CATEGORIES[cat_key]
    else:
        tx_type = "expense"
        if cat_key not in db.EXPENSE_CATEGORIES:
            cat_key = "lainnya"
            cat_display = db.EXPENSE_CATEGORIES.get("lainnya", "📦 Lainnya")
        else:
            cat_display = db.EXPENSE_CATEGORIES[cat_key]

    return tx_type, cat_key, cat_display


# ══════════════════════════════════════════════
# Command Handlers
# ══════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    user = update.effective_user
    await db.init_db()

    welcome = (
        f"👋 Halo, **{user.first_name}**! Aku Financial Assistant kamu.\n\n"
        "🎯 **Cara pakai:**\n"
        "Tinggal ketik transaksi kamu, aku parse otomatis:\n\n"
        "💸 _Pengeluaran:_\n"
        '• `makan siang 35rb bri`\n'
        '• `gojek 15k gopay`\n'
        '• `belanja shopee 250rb bca`\n\n'
        "💵 _Pemasukan:_\n"
        '• `gaji 5jt bsi`\n'
        '• `+ freelance 2.5jt mandiri`\n'
        '• `bonus 500rb bca`\n\n'
        "💡 Sebut nama rekening (BRI, BSI, BCA, GoPay, dll) dan saldo otomatis terupdate!\n\n"
        "📋 Ketik /help untuk daftar semua perintah"
    )
    await update.message.reply_text(welcome, parse_mode="Markdown")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    help_text = (
        "📖 **Panduan Financial Assistant**\n\n"

        "**💬 Format Input Natural:**\n"
        "Cukup ketik deskripsi + nominal + nama rekening:\n"
        '• `makan 35rb bri` → 🍔 Makanan, potong saldo BRI\n'
        '• `gojek 15k gopay` → 🚗 Transport, potong saldo GoPay\n'
        '• `gaji 5jt bsi` → 💼 Gaji, tambah saldo BSI\n'
        '• `netflix 54rb` → 🎮 Hiburan (tanpa rekening)\n\n'

        "**🔢 Format Angka:**\n"
        "• `rb` / `ribu` / `k` = ribuan\n"
        "• `jt` / `juta` = jutaan\n"
        "• `1.500.000` = langsung\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n"
        "📋 **DAFTAR PERINTAH**\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        "**📝 Catat Transaksi:**\n"
        "/tambah `[desc] [nominal]` — Pengeluaran\n"
        "/masuk `[desc] [nominal]` — Pemasukan\n\n"

        "**📊 Laporan:**\n"
        "/ringkasan — Ringkasan 30 hari\n"
        "/hari — Pengeluaran hari ini\n"
        "/kategori — Breakdown per kategori\n"
        "/analisis — Analisis perilaku keuangan\n"
        "/export — Download Excel\n\n"

        "**✏️ Edit & Kelola Transaksi:**\n"
        "/daftar — Lihat transaksi + ID\n"
        "/edit `[id] [jumlah_baru]` — Edit jumlah\n"
        "/edit `[id] desc [teks]` — Edit deskripsi\n"
        "/hapus — Hapus transaksi terakhir\n"
        "/hapusid `[id]` — Hapus transaksi spesifik\n\n"

        "**💳 Rekening & Aset:**\n"
        "/rekening — Lihat semua rekening & total\n"
        "/tambahakun `[nama] [saldo]` — Tambah akun\n"
        "/editakun `[nama] [saldo_baru]` — Edit saldo\n"
        "/hapusakun `[nama]` — Hapus akun\n\n"

        "**🎯 Tabungan:**\n"
        "/tabung `[nama] [target]` — Buat goal\n"
        "/setor `[nama] [jumlah]` — Setor tabungan\n"
        "/tarik `[nama] [jumlah]` — Tarik tabungan\n"
        "/tabungan — Lihat semua tabungan\n\n"

        "**💰 Budget:**\n"
        "/budget `[kategori] [limit]` — Set budget\n\n"

        "**🌐 Lainnya:**\n"
        "/dashboard — Buka web dashboard\n"
        "/help — Panduan ini"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def cmd_add_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /tambah or /t command."""
    if not context.args:
        await update.message.reply_text(
            "⚠️ Format: `/tambah [deskripsi] [nominal]`\n"
            "Contoh: `/tambah makan siang 35rb`",
            parse_mode="Markdown",
        )
        return

    text = " ".join(context.args)
    await process_transaction(update, text, force_type="expense")


async def cmd_add_income(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /masuk or /m command."""
    if not context.args:
        await update.message.reply_text(
            "⚠️ Format: `/masuk [deskripsi] [nominal]`\n"
            "Contoh: `/masuk gaji 5jt`",
            parse_mode="Markdown",
        )
        return

    text = " ".join(context.args)
    await process_transaction(update, text, force_type="income")


async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /ringkasan command."""
    user_id = update.effective_user.id
    summary = await db.get_summary(user_id, days=30)

    balance_emoji = "📈" if summary["balance"] >= 0 else "📉"
    savings_emoji = "🟢" if summary["savings_rate"] >= 20 else "🟡" if summary["savings_rate"] >= 0 else "🔴"

    text = (
        "📊 **Ringkasan Keuangan (30 Hari)**\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💵 Pemasukan: **{format_rupiah(summary['total_income'])}**\n"
        f"💸 Pengeluaran: **{format_rupiah(summary['total_expense'])}**\n"
        f"{balance_emoji} Saldo: **{format_rupiah(summary['balance'])}**\n"
        f"{savings_emoji} Savings Rate: **{summary['savings_rate']}%**\n\n"
        f"📝 Total Transaksi: {summary['transaction_count']}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💡 _Ketik /kategori untuk detail per kategori_"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /hari command."""
    user_id = update.effective_user.id
    today = await db.get_today_spending(user_id)

    if today["total"] == 0:
        await update.message.reply_text(
            "✨ **Belum ada pengeluaran hari ini!**\n"
            "_Hemat ya!_ 💰",
            parse_mode="Markdown",
        )
        return

    lines = [
        f"📅 **Pengeluaran Hari Ini**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
    ]

    for cat in today["categories"]:
        lines.append(f"• {cat['category']}: **{format_rupiah(cat['total'])}** ({cat['count']}x)")

    lines.append(f"\n💸 **Total: {format_rupiah(today['total'])}**")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /kategori command."""
    user_id = update.effective_user.id
    breakdown = await db.get_category_breakdown(user_id, days=30)

    if not breakdown:
        await update.message.reply_text(
            "📭 Belum ada data pengeluaran dalam 30 hari terakhir.",
            parse_mode="Markdown",
        )
        return

    total = sum(c["total"] for c in breakdown)
    lines = [
        "📂 **Breakdown Kategori (30 Hari)**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
    ]

    for cat in breakdown:
        pct = (cat["total"] / total * 100) if total > 0 else 0
        bar_length = int(pct / 5)
        bar = "█" * bar_length + "░" * (20 - bar_length)
        lines.append(
            f"**{cat['category']}**\n"
            f"`{bar}` {pct:.1f}%\n"
            f"{format_rupiah(cat['total'])} ({cat['count']}x)\n"
        )

    lines.append(f"━━━━━━━━━━━━━━━━━━━━\n💸 **Total: {format_rupiah(total)}**")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /export command."""
    user_id = update.effective_user.id
    await update.message.reply_text("⏳ Generating Excel report...")

    try:
        filepath = await db.export_to_excel(user_id)
        with open(filepath, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=filepath.split("\\")[-1].split("/")[-1],
                caption="📊 Here's your financial report! 💰",
            )
    except Exception as e:
        logger.error(f"Export failed: {e}")
        await update.message.reply_text(f"❌ Export gagal: {str(e)}")


async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /hapus command."""
    user_id = update.effective_user.id
    tx = await db.delete_last_transaction(user_id)

    if not tx:
        await update.message.reply_text("📭 Tidak ada transaksi untuk dihapus.")
        return

    type_text = "Pemasukan" if tx["type"] == "income" else "Pengeluaran"
    text = (
        "🗑️ **Transaksi Dihapus:**\n"
        f"• {type_text}: {tx['category']}\n"
        f"• Jumlah: {format_rupiah(tx['amount'])}\n"
        f"• Deskripsi: {tx['description']}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

    # Notify dashboard
    if sse_notify:
        await sse_notify({"event": "transaction_deleted", "user_id": user_id})


async def cmd_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /dashboard command."""
    from dotenv import load_dotenv
    import os
    load_dotenv()
    port = os.getenv("DASHBOARD_PORT", "8000")

    await update.message.reply_text(
        f"📊 **Dashboard Keuangan Kamu**\n\n"
        f"🔗 Buka di browser:\n"
        f"`http://localhost:{port}`\n\n"
        f"_Dashboard update real-time setiap kamu chat!_ ⚡",
        parse_mode="Markdown",
    )


# ══════════════════════════════════════════════
# Natural Language Message Handler
# ══════════════════════════════════════════════

async def process_transaction(
    update: Update,
    text: str,
    force_type: str | None = None,
):
    """Process a transaction from natural language text."""
    user_id = update.effective_user.id

    # Parse amount
    amount = parse_amount(text)
    if amount is None or amount <= 0:
        return False

    # Remove the amount part to get description
    desc = re.sub(r'\d+[.,]?\d*\s*(rb|ribu|k|jt|juta|m)\b', '', text, flags=re.IGNORECASE).strip()
    desc = re.sub(r'\d{1,3}(?:\.\d{3})+', '', desc).strip()
    desc = re.sub(r'\d{4,}', '', desc).strip()
    desc = re.sub(r'\d+', '', desc).strip()
    desc = re.sub(r'\s+', ' ', desc).strip()

    if not desc:
        desc = "Transaksi"

    # Detect type and category
    if force_type:
        tx_type = force_type
        cat_key, cat_display = db.auto_categorize(desc)
        if tx_type == "income" and cat_key not in db.INCOME_CATEGORIES:
            cat_key = "lainnya"
            cat_display = db.INCOME_CATEGORIES["lainnya"]
        elif tx_type == "expense" and cat_key not in db.EXPENSE_CATEGORIES:
            cat_key = "lainnya"
            cat_display = db.EXPENSE_CATEGORIES["lainnya"]
        else:
            if tx_type == "income":
                cat_display = db.INCOME_CATEGORIES.get(cat_key, cat_display)
            else:
                cat_display = db.EXPENSE_CATEGORIES.get(cat_key, cat_display)
    else:
        tx_type, cat_key, cat_display = detect_type_and_category(desc, raw_text=text)

    # Detect account mentioned in text
    account_name = await db.detect_account_in_text(user_id, text)

    # Save to database
    tx = await db.add_transaction(
        user_id=user_id,
        tx_type=tx_type,
        category=cat_display,
        amount=amount,
        description=desc.capitalize(),
        account_name=account_name,
    )

    # Build confirmation message
    type_emoji = "💵" if tx_type == "income" else "💸"
    type_text = "Pemasukan" if tx_type == "income" else "Pengeluaran"
    toggle_target = "Pengeluaran" if tx_type == "income" else "Pemasukan"

    acc_info = tx.get("account_info")
    acc_text = ""
    if acc_info:
        acc_text = f"\n💳 Rekening: {acc_info['icon']} **{acc_info['name']}** (Saldo: **{format_rupiah(acc_info['balance'])}**)"

    confirm_text = (
        f"{type_emoji} **{type_text} Dicatat!**\n\n"
        f"📂 Kategori: {cat_display}\n"
        f"💰 Jumlah: **{format_rupiah(amount)}**\n"
        f"📝 Deskripsi: {desc.capitalize()}"
        f"{acc_text}\n"
        f"🕐 {datetime.now().strftime('%d %b %Y, %H:%M')}"
    )

    # Inline keyboard for actions
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"🔄 Ubah ke {toggle_target}", callback_data=f"toggle_{tx['id']}"),
        ],
        [
            InlineKeyboardButton("🗑️ Hapus", callback_data=f"delete_{tx['id']}"),
            InlineKeyboardButton("📊 Ringkasan", callback_data="summary"),
        ]
    ])

    await update.message.reply_text(confirm_text, parse_mode="Markdown", reply_markup=keyboard)

    # Notify dashboard via SSE
    if sse_notify:
        await sse_notify({
            "event": "new_transaction",
            "user_id": user_id,
            "transaction": tx,
        })
        if acc_info:
            await sse_notify({"event": "account_updated", "user_id": user_id})

    return True


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle plain text messages — natural language transaction input."""
    text = update.message.text.strip()

    if not text:
        return

    result = await process_transaction(update, text)

    if not result:
        await update.message.reply_text(
            "🤔 Aku gak bisa baca transaksi dari pesan itu.\n\n"
            "Coba format:\n"
            '• `makan siang 35rb bri` (Pengeluaran BRI)\n'
            '• `+ gaji 5jt bsi` (Pemasukan BSI)\n'
            '• `gopay 50k jajan` (Pengeluaran GoPay)\n\n'
            "_Ketik /help untuk bantuan lengkap_",
            parse_mode="Markdown",
        )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard callbacks."""
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = update.effective_user.id

    if data.startswith("toggle_"):
        tx_id = int(data.split("_")[1])
        tx = await db.toggle_transaction_type(tx_id)
        if tx:
            type_emoji = "💵" if tx["type"] == "income" else "💸"
            type_text = "Pemasukan" if tx["type"] == "income" else "Pengeluaran"
            toggle_target = "Pengeluaran" if tx["type"] == "income" else "Pemasukan"

            acc_info = tx.get("account_info")
            acc_text = ""
            if acc_info:
                acc_text = f"\n💳 Rekening: {acc_info['icon']} **{acc_info['name']}** (Saldo: **{format_rupiah(acc_info['balance'])}**)"

            confirm_text = (
                f"{type_emoji} **Tipe Diubah ke {type_text}!**\n\n"
                f"📂 Kategori: {tx['category']}\n"
                f"💰 Jumlah: **{format_rupiah(tx['amount'])}**\n"
                f"📝 Deskripsi: {tx['description']}"
                f"{acc_text}\n"
                f"🕐 {datetime.now().strftime('%d %b %Y, %H:%M')}"
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"🔄 Ubah ke {toggle_target}", callback_data=f"toggle_{tx['id']}")],
                [
                    InlineKeyboardButton("🗑️ Hapus", callback_data=f"delete_{tx['id']}"),
                    InlineKeyboardButton("📊 Ringkasan", callback_data="summary"),
                ]
            ])
            await query.edit_message_text(confirm_text, parse_mode="Markdown", reply_markup=keyboard)

            if sse_notify:
                await sse_notify({"event": "new_transaction", "user_id": user_id})
                if acc_info:
                    await sse_notify({"event": "account_updated", "user_id": user_id})

    elif data.startswith("delete_"):
        tx_id = int(data.split("_")[1])
        tx = await db.delete_last_transaction(user_id)
        if tx:
            await query.edit_message_text(
                f"🗑️ Transaksi dihapus: {tx['description']} ({format_rupiah(tx['amount'])})",
                parse_mode="Markdown",
            )
            if sse_notify:
                await sse_notify({"event": "transaction_deleted", "user_id": user_id})
                await sse_notify({"event": "account_updated", "user_id": user_id})
        else:
            await query.edit_message_text("❌ Transaksi tidak ditemukan.")

    elif data == "summary":
        summary = await db.get_summary(user_id, days=30)
        balance_emoji = "📈" if summary["balance"] >= 0 else "📉"
        text = (
            "📊 **Ringkasan 30 Hari**\n\n"
            f"💵 Pemasukan: {format_rupiah(summary['total_income'])}\n"
            f"💸 Pengeluaran: {format_rupiah(summary['total_expense'])}\n"
            f"{balance_emoji} Saldo: {format_rupiah(summary['balance'])}\n"
            f"📊 Savings Rate: {summary['savings_rate']}%"
        )
        await query.edit_message_text(text, parse_mode="Markdown")



# ══════════════════════════════════════════════
# Savings Commands
# ══════════════════════════════════════════════

async def cmd_tabung(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /tabung command — create savings goal."""
    if len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ Format: `/tabung [nama] [target]`\n"
            "Contoh: `/tabung Liburan 5jt`\n"
            "Contoh: `/tabung Dana Darurat 10jt`",
            parse_mode="Markdown",
        )
        return

    amount = parse_amount(context.args[-1])
    if amount is None:
        await update.message.reply_text("⚠️ Nominal tidak valid. Contoh: `5jt`, `500rb`", parse_mode="Markdown")
        return

    name = " ".join(context.args[:-1]).strip().title()
    if not name:
        name = "Tabungan"

    user_id = update.effective_user.id
    goal = await db.add_savings_goal(user_id, name, amount)

    await update.message.reply_text(
        f"🏦 **Goal Tabungan Dibuat!**\n\n"
        f"{goal['icon']} **{name}**\n"
        f"🎯 Target: **{format_rupiah(amount)}**\n"
        f"💰 Terkumpul: Rp 0 (0%)\n\n"
        f"_Setor dengan:_ `/setor {name} [jumlah]`",
        parse_mode="Markdown",
    )

    if sse_notify:
        await sse_notify({"event": "savings_updated", "user_id": user_id})


async def cmd_setor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /setor command — deposit to savings."""
    if len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ Format: `/setor [nama goal] [jumlah]`\n"
            "Contoh: `/setor Liburan 500rb`",
            parse_mode="Markdown",
        )
        return

    amount = parse_amount(context.args[-1])
    if amount is None:
        await update.message.reply_text("⚠️ Nominal tidak valid.", parse_mode="Markdown")
        return

    goal_name = " ".join(context.args[:-1]).strip()
    user_id = update.effective_user.id
    goal = await db.deposit_savings(user_id, goal_name, amount)

    if not goal:
        await update.message.reply_text(
            f"❌ Goal `{goal_name}` tidak ditemukan.\n"
            f"Ketik /tabungan untuk lihat daftar goals.",
            parse_mode="Markdown",
        )
        return

    bar_len = int(min(goal["progress"], 100) / 5)
    bar = "█" * bar_len + "░" * (20 - bar_len)

    await update.message.reply_text(
        f"✅ **Setor Berhasil!**\n\n"
        f"{goal['icon']} **{goal['name']}**\n"
        f"💰 +{format_rupiah(amount)}\n"
        f"`{bar}` {goal['progress']:.1f}%\n"
        f"Terkumpul: {format_rupiah(goal['current_amount'])} / {format_rupiah(goal['target_amount'])}",
        parse_mode="Markdown",
    )

    if sse_notify:
        await sse_notify({"event": "savings_updated", "user_id": user_id})


async def cmd_tarik(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /tarik command — withdraw from savings."""
    if len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ Format: `/tarik [nama goal] [jumlah]`\n"
            "Contoh: `/tarik Liburan 200rb`",
            parse_mode="Markdown",
        )
        return

    amount = parse_amount(context.args[-1])
    if amount is None:
        await update.message.reply_text("⚠️ Nominal tidak valid.", parse_mode="Markdown")
        return

    goal_name = " ".join(context.args[:-1]).strip()
    user_id = update.effective_user.id
    goal = await db.withdraw_savings(user_id, goal_name, amount)

    if not goal:
        await update.message.reply_text(f"❌ Goal `{goal_name}` tidak ditemukan.", parse_mode="Markdown")
        return

    await update.message.reply_text(
        f"💸 **Penarikan Berhasil**\n\n"
        f"{goal['icon']} **{goal['name']}**\n"
        f"💸 -{format_rupiah(amount)}\n"
        f"Sisa: {format_rupiah(goal['current_amount'])} / {format_rupiah(goal['target_amount'])} ({goal['progress']:.1f}%)",
        parse_mode="Markdown",
    )

    if sse_notify:
        await sse_notify({"event": "savings_updated", "user_id": user_id})


async def cmd_tabungan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /tabungan command — list all savings goals."""
    user_id = update.effective_user.id
    goals = await db.get_savings_goals(user_id)

    if not goals:
        await update.message.reply_text(
            "📭 Belum ada goal tabungan.\n"
            "Buat dengan: `/tabung [nama] [target]`\n"
            "Contoh: `/tabung Dana Darurat 10jt`",
            parse_mode="Markdown",
        )
        return

    lines = ["🏦 **Goal Tabungan Kamu**\n━━━━━━━━━━━━━━━━━━━━\n"]
    total_saved = 0
    total_target = 0

    for g in goals:
        bar_len = int(min(g["progress"], 100) / 5)
        bar = "█" * bar_len + "░" * (20 - bar_len)
        lines.append(
            f"{g['icon']} **{g['name']}**\n"
            f"`{bar}` {g['progress']:.1f}%\n"
            f"{format_rupiah(g['current_amount'])} / {format_rupiah(g['target_amount'])}\n"
        )
        total_saved += g["current_amount"]
        total_target += g["target_amount"]

    overall = round(total_saved / total_target * 100, 1) if total_target > 0 else 0
    lines.append(
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 **Total: {format_rupiah(total_saved)} / {format_rupiah(total_target)} ({overall}%)**"
    )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ══════════════════════════════════════════════
# Budget Commands
# ══════════════════════════════════════════════

async def cmd_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /budget command — set or view budgets."""
    user_id = update.effective_user.id

    if not context.args:
        data = await db.get_budget_vs_actual(user_id)
        if not data:
            await update.message.reply_text(
                "📭 Belum ada budget yang di-set.\n\n"
                "Set dengan: `/budget [kategori] [limit bulanan]`\n"
                "Contoh:\n"
                "• `/budget makanan 1.5jt`\n"
                "• `/budget transport 500rb`\n"
                "• `/budget hiburan 300rb`",
                parse_mode="Markdown",
            )
            return

        lines = ["💰 **Budget vs Aktual Bulan Ini**\n━━━━━━━━━━━━━━━━━━━━\n"]
        for item in data:
            if not item["has_budget"]:
                continue
            status_icon = "🟢" if item["status"] == "safe" else "🟡" if item["status"] == "warning" else "🔴"
            bar_len = int(min(item["percentage"], 100) / 5)
            bar = "█" * bar_len + "░" * (20 - bar_len)
            lines.append(
                f"{status_icon} **{item['category']}**\n"
                f"`{bar}` {item['percentage']:.0f}%\n"
                f"Spent: {format_rupiah(item['spent'])} / {format_rupiah(item['budget'])}\n"
            )

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ Format: `/budget [kategori] [limit]`\n"
            "Contoh: `/budget makanan 1.5jt`",
            parse_mode="Markdown",
        )
        return

    amount = parse_amount(context.args[-1])
    if amount is None:
        await update.message.reply_text("⚠️ Nominal tidak valid.", parse_mode="Markdown")
        return

    cat_input = " ".join(context.args[:-1]).strip().lower()
    cat_key, cat_display = db.auto_categorize(cat_input)
    if cat_key == "lainnya" and cat_input != "lainnya":
        cat_display = cat_input.title()

    category_name = db.EXPENSE_CATEGORIES.get(cat_key, cat_display)
    await db.set_budget(user_id, category_name, amount)

    await update.message.reply_text(
        f"✅ **Budget Di-set!**\n\n"
        f"📂 {category_name}\n"
        f"💰 Limit: **{format_rupiah(amount)}** / bulan\n\n"
        f"_Ketik /budget untuk lihat semua budget_",
        parse_mode="Markdown",
    )

    if sse_notify:
        await sse_notify({"event": "budget_updated", "user_id": user_id})


# ══════════════════════════════════════════════
# Analysis Command
# ══════════════════════════════════════════════

async def cmd_analisis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /analisis command — behavior analysis."""
    user_id = update.effective_user.id
    analysis = await db.get_behavior_analysis(user_id)

    score = analysis["score"]
    if score >= 80:
        score_emoji = "🟢"
        score_label = "Excellent"
    elif score >= 60:
        score_emoji = "🟡"
        score_label = "Good"
    elif score >= 40:
        score_emoji = "🟠"
        score_label = "Perlu Perbaikan"
    else:
        score_emoji = "🔴"
        score_label = "Kritis"

    trend = analysis["overall_trend"]
    trend_emoji = "📈" if trend == "up" else "📉" if trend == "down" else "➡️"
    change = analysis["overall_change"]
    change_text = f"+{change}%" if change > 0 else f"{change}%"

    lines = [
        f"🧠 **Analisis Keuangan Bulan Ini**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{score_emoji} **Spending Score: {score}/100** ({score_label})\n"
        f"{trend_emoji} Trend: {change_text} dari bulan lalu\n"
        f"📊 Rata-rata harian: {format_rupiah(analysis['daily_average'])}\n\n"
    ]

    if analysis["top_categories"]:
        lines.append("🏆 **Top Pengeluaran:**\n")
        for i, cat in enumerate(analysis["top_categories"], 1):
            t = "📈" if cat["trend"] == "up" else "📉" if cat["trend"] == "down" else "➡️"
            lines.append(
                f"{i}. {cat['category']}: {format_rupiah(cat['amount'])} "
                f"({t} {'+' if cat['change_pct'] > 0 else ''}{cat['change_pct']}%)\n"
            )

    if analysis["recommendations"]:
        lines.append("\n💡 **Rekomendasi:**\n")
        for rec in analysis["recommendations"][:5]:
            lines.append(f"{rec['icon']} **{rec['title']}**\n_{rec['message']}_\n\n")

    await update.message.reply_text("".join(lines), parse_mode="Markdown")


# ══════════════════════════════════════════════
# Bank & E-Wallet Account Commands
# ══════════════════════════════════════════════

async def cmd_akun(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /akun command — view all accounts and total balance."""
    user_id = update.effective_user.id
    accounts = await db.get_accounts(user_id)

    if not accounts:
        await update.message.reply_text(
            "📭 Belum ada daftar rekening/akun tabungan.\n\n"
            "Tambah dengan: `/tambahakun [nama] [saldo]`\n"
            "Contoh:\n"
            "• `/tambahakun BCA 5jt`\n"
            "• `/tambahakun GoPay 250rb`\n"
            "• `/tambahakun Bibit 10jt`",
            parse_mode="Markdown",
        )
        return

    lines = ["🏛️ **Lokasi Tabungan & Rekening Kamu**\n━━━━━━━━━━━━━━━━━━━━\n"]
    total_networth = 0

    for acc in accounts:
        lines.append(
            f"{acc['icon']} **{acc['name']}**: **{format_rupiah(acc['balance'])}**\n"
        )
        total_networth += acc["balance"]

    lines.append(
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 **Total Net Worth: {format_rupiah(total_networth)}**"
    )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_tambahakun(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /tambahakun command — add or update an account balance."""
    if len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ Format: `/tambahakun [nama] [saldo]`\n"
            "Contoh: `/tambahakun BCA 5jt`\n"
            "Contoh: `/tambahakun GoPay 250rb`",
            parse_mode="Markdown",
        )
        return

    amount = parse_amount(context.args[-1])
    if amount is None:
        await update.message.reply_text("⚠️ Nominal saldo tidak valid.", parse_mode="Markdown")
        return

    name = " ".join(context.args[:-1]).strip().upper()
    user_id = update.effective_user.id

    acc = await db.add_or_update_account(user_id, name, amount)

    await update.message.reply_text(
        f"✅ **Rekening/Akun Diperbarui!**\n\n"
        f"{acc['icon']} **{acc['name']}**\n"
        f"💰 Saldo: **{format_rupiah(amount)}**\n\n"
        f"_Ketik /akun untuk lihat seluruh aset kamu_",
        parse_mode="Markdown",
    )

    if sse_notify:
        await sse_notify({"event": "account_updated", "user_id": user_id})


async def cmd_hapusakun(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /hapusakun command — delete an account."""
    if not context.args:
        await update.message.reply_text("⚠️ Format: `/hapusakun [nama]`", parse_mode="Markdown")
        return

    name = " ".join(context.args).strip()
    user_id = update.effective_user.id
    success = await db.delete_account(user_id, name)

    if success:
        await update.message.reply_text(f"🗑️ Akun `{name}` berhasil dihapus.", parse_mode="Markdown")
        if sse_notify:
            await sse_notify({"event": "account_updated", "user_id": user_id})
    else:
        await update.message.reply_text(f"❌ Akun `{name}` tidak ditemukan.", parse_mode="Markdown")


# ══════════════════════════════════════════════
# Transaction Management Commands
# ══════════════════════════════════════════════

async def cmd_daftar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /daftar command — list recent transactions with IDs."""
    user_id = update.effective_user.id
    limit = 10
    if context.args:
        try:
            limit = min(int(context.args[0]), 20)
        except ValueError:
            pass

    transactions = await db.get_transactions(user_id, limit=limit)

    if not transactions:
        await update.message.reply_text(
            "📭 Belum ada transaksi.\n_Coba kirim pesan seperti_ `makan 25rb bri`",
            parse_mode="Markdown",
        )
        return

    lines = ["📋 **Daftar Transaksi Terakhir**\n━━━━━━━━━━━━━━━━━━━━\n"]

    for tx in transactions:
        type_emoji = "💵" if tx["type"] == "income" else "💸"
        acc_tag = f" [{tx['account_name']}]" if tx.get("account_name") else ""
        date_str = tx["created_at"][:10] if tx.get("created_at") else ""
        lines.append(
            f"{type_emoji} `#{tx['id']}` — **{format_rupiah(tx['amount'])}**\n"
            f"   {tx.get('description', '-')}{acc_tag} ({date_str})\n"
        )

    lines.append(
        "━━━━━━━━━━━━━━━━━━━━\n"
        "✏️ Edit: `/edit [id] [jumlah_baru]`\n"
        "🗑️ Hapus: `/hapusid [id]`"
    )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /edit command — edit a transaction's amount or description."""
    if len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ Format:\n"
            "• `/edit [id] [jumlah_baru]`\n"
            "• `/edit [id] desc [deskripsi_baru]`\n\n"
            "Contoh:\n"
            "• `/edit 5 50rb` → Ubah jumlah transaksi #5 jadi Rp 50.000\n"
            "• `/edit 5 desc makan siang` → Ubah deskripsi\n\n"
            "💡 _Ketik /daftar untuk lihat ID transaksi_",
            parse_mode="Markdown",
        )
        return

    user_id = update.effective_user.id

    try:
        tx_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID harus berupa angka. Ketik `/daftar` untuk lihat.", parse_mode="Markdown")
        return

    # Check if editing description
    if context.args[1].lower() == "desc":
        new_desc = " ".join(context.args[2:]).strip()
        if not new_desc:
            await update.message.reply_text("⚠️ Deskripsi tidak boleh kosong.", parse_mode="Markdown")
            return
        tx = await db.edit_transaction(user_id, tx_id, new_description=new_desc)
    else:
        # Editing amount
        amount_text = " ".join(context.args[1:])
        new_amount = parse_amount(amount_text)
        if new_amount is None or new_amount <= 0:
            await update.message.reply_text("❌ Jumlah tidak valid.", parse_mode="Markdown")
            return
        tx = await db.edit_transaction(user_id, tx_id, new_amount=new_amount)

    if not tx:
        await update.message.reply_text(f"❌ Transaksi `#{tx_id}` tidak ditemukan.", parse_mode="Markdown")
        return

    type_emoji = "💵" if tx["type"] == "income" else "💸"
    type_text = "Pemasukan" if tx["type"] == "income" else "Pengeluaran"
    await update.message.reply_text(
        f"✅ **Transaksi #{tx_id} Berhasil Diedit!**\n\n"
        f"{type_emoji} Tipe: {type_text}\n"
        f"💰 Jumlah: **{format_rupiah(tx['amount'])}**\n"
        f"📝 Deskripsi: {tx['description']}",
        parse_mode="Markdown",
    )

    if sse_notify:
        await sse_notify({"event": "new_transaction", "user_id": user_id})
        await sse_notify({"event": "account_updated", "user_id": user_id})


async def cmd_hapusid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /hapusid command — delete a transaction by ID."""
    if not context.args:
        await update.message.reply_text(
            "⚠️ Format: `/hapusid [id]`\n"
            "Contoh: `/hapusid 5`\n\n"
            "💡 _Ketik /daftar untuk lihat ID transaksi_",
            parse_mode="Markdown",
        )
        return

    user_id = update.effective_user.id

    try:
        tx_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID harus berupa angka.", parse_mode="Markdown")
        return

    tx = await db.delete_transaction_by_id(user_id, tx_id)
    if not tx:
        await update.message.reply_text(f"❌ Transaksi `#{tx_id}` tidak ditemukan.", parse_mode="Markdown")
        return

    type_text = "Pemasukan" if tx["type"] == "income" else "Pengeluaran"
    await update.message.reply_text(
        f"🗑️ **Transaksi #{tx_id} Dihapus!**\n\n"
        f"• {type_text}: {format_rupiah(tx['amount'])}\n"
        f"• Deskripsi: {tx['description']}",
        parse_mode="Markdown",
    )

    if sse_notify:
        await sse_notify({"event": "transaction_deleted", "user_id": user_id})
        await sse_notify({"event": "account_updated", "user_id": user_id})


async def cmd_editakun(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /editakun command — set account balance directly."""
    if len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ Format: `/editakun [nama] [saldo_baru]`\n"
            "Contoh: `/editakun BRI 5jt`\n"
            "Contoh: `/editakun GoPay 500rb`",
            parse_mode="Markdown",
        )
        return

    user_id = update.effective_user.id
    new_balance = parse_amount(context.args[-1])
    if new_balance is None:
        await update.message.reply_text("❌ Jumlah saldo tidak valid.", parse_mode="Markdown")
        return

    name = " ".join(context.args[:-1]).strip()
    acc = await db.add_or_update_account(user_id, name, new_balance)

    await update.message.reply_text(
        f"✅ **Saldo Akun Diperbarui!**\n\n"
        f"{acc['icon']} **{acc['name']}**\n"
        f"💰 Saldo Baru: **{format_rupiah(acc['balance'])}**",
        parse_mode="Markdown",
    )

    if sse_notify:
        await sse_notify({"event": "account_updated", "user_id": user_id})


def create_bot(token: str):
    """Create and configure the Telegram bot application."""
    req = HTTPXRequest(
        connect_timeout=60.0,
        read_timeout=60.0,
        write_timeout=60.0,
        pool_timeout=60.0,
    )
    app = (
        ApplicationBuilder()
        .token(token)
        .request(req)
        .get_updates_request(req)
        .build()
    )

    # Command handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler(["tambah", "t"], cmd_add_expense))
    app.add_handler(CommandHandler(["masuk", "m"], cmd_add_income))
    app.add_handler(CommandHandler("ringkasan", cmd_summary))
    app.add_handler(CommandHandler("hari", cmd_today))
    app.add_handler(CommandHandler("kategori", cmd_categories))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CommandHandler("hapus", cmd_delete))
    app.add_handler(CommandHandler("dashboard", cmd_dashboard))

    # v2: Savings commands
    app.add_handler(CommandHandler("tabung", cmd_tabung))
    app.add_handler(CommandHandler("setor", cmd_setor))
    app.add_handler(CommandHandler("tarik", cmd_tarik))
    app.add_handler(CommandHandler("tabungan", cmd_tabungan))

    # v2: Budget & Analysis commands
    app.add_handler(CommandHandler("budget", cmd_budget))
    app.add_handler(CommandHandler("analisis", cmd_analisis))

    # Accounts & Bank commands
    app.add_handler(CommandHandler(["akun", "rekening"], cmd_akun))
    app.add_handler(CommandHandler("tambahakun", cmd_tambahakun))
    app.add_handler(CommandHandler("hapusakun", cmd_hapusakun))
    app.add_handler(CommandHandler("editakun", cmd_editakun))

    # Transaction management commands
    app.add_handler(CommandHandler(["daftar", "list"], cmd_daftar))
    app.add_handler(CommandHandler("edit", cmd_edit))
    app.add_handler(CommandHandler("hapusid", cmd_hapusid))

    # Callback handler for inline keyboards
    app.add_handler(CallbackQueryHandler(handle_callback))

    # Natural language message handler (must be last)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    return app
