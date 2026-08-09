/**
 * Financial Assistant v2 — Dashboard Frontend
 * Real-time dashboard with Chart.js, SSE, Savings, Budget & Behavior Analysis
 */

// ═══════════════════════════════════════════
// Configuration & State
// ═══════════════════════════════════════════

const API = {
    summary: '/api/summary',
    transactions: '/api/transactions',
    daily: '/api/daily',
    categories: '/api/categories',
    monthly: '/api/monthly',
    savings: '/api/savings',
    budgets: '/api/budgets',
    accounts: '/api/accounts',
    analysis: '/api/analysis',
    trend: '/api/trend',
    sse: '/sse',
};

let trendChart = null;
let categoryChart = null;
let monthlyChart = null;
let sseConnection = null;
let currentPeriod = 'daily';

// Chart.js color palette
const COLORS = {
    income: { main: '#10b981', gradient: ['rgba(16, 185, 129, 0.3)', 'rgba(16, 185, 129, 0.01)'] },
    expense: { main: '#f43f5e', gradient: ['rgba(244, 63, 94, 0.3)', 'rgba(244, 63, 94, 0.01)'] },
    categories: [
        '#6366f1', '#8b5cf6', '#ec4899', '#f43f5e', '#f59e0b',
        '#10b981', '#06b6d4', '#3b82f6', '#a855f7', '#14b8a6',
    ],
};

// Chart.js default config for dark theme
Chart.defaults.color = '#cbd5e1';
Chart.defaults.borderColor = 'rgba(255, 255, 255, 0.06)';
Chart.defaults.font.family = "'Plus Jakarta Sans', sans-serif";
Chart.defaults.font.size = 12;

// ═══════════════════════════════════════════
// Utility Functions
// ═══════════════════════════════════════════

function formatRupiah(amount) {
    if (amount === 0) return 'Rp 0';

    const abs = Math.abs(amount);
    const sign = amount < 0 ? '-' : '';

    if (abs >= 1_000_000_000) {
        return `${sign}Rp ${(abs / 1_000_000_000).toFixed(1)}M`;
    }
    if (abs >= 1_000_000) {
        const val = abs / 1_000_000;
        return `${sign}Rp ${val % 1 === 0 ? val.toFixed(0) : val.toFixed(1)} jt`;
    }
    if (abs >= 1_000) {
        const val = abs / 1_000;
        return `${sign}Rp ${val % 1 === 0 ? val.toFixed(0) : val.toFixed(1)} rb`;
    }
    return `${sign}Rp ${abs.toLocaleString('id-ID')}`;
}

function formatRupiahFull(amount) {
    const sign = amount < 0 ? '-' : '';
    return `${sign}Rp ${Math.abs(amount).toLocaleString('id-ID', { maximumFractionDigits: 0 })}`;
}

function formatDate(dateStr) {
    const d = new Date(dateStr);
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun',
                    'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];
    return `${d.getDate()} ${months[d.getMonth()]} ${d.getFullYear()}`;
}

function formatTime(dateStr) {
    const d = new Date(dateStr);
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function formatDateShort(dateStr) {
    if (!dateStr) return '';
    if (dateStr.length === 4) return dateStr; // Year
    const parts = dateStr.split('-');
    if (parts.length === 2) {
        const months = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];
        return `${months[parseInt(parts[1]) - 1]} ${parts[0].slice(2)}`;
    }
    const d = new Date(dateStr);
    return `${d.getDate()}/${d.getMonth() + 1}`;
}

function updateHeaderDate() {
    const now = new Date();
    const days = ['Minggu', 'Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu'];
    const months = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni',
                    'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember'];
    document.getElementById('headerDate').textContent =
        `${days[now.getDay()]}, ${now.getDate()} ${months[now.getMonth()]} ${now.getFullYear()}`;
}

function animateValue(element, start, end, duration, formatter) {
    const range = end - start;
    const startTime = performance.now();

    function update(currentTime) {
        const elapsed = currentTime - startTime;
        const progress = Math.min(elapsed / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3);
        const current = start + range * eased;

        element.textContent = formatter ? formatter(current) : Math.round(current);

        if (progress < 1) {
            requestAnimationFrame(update);
        }
    }

    requestAnimationFrame(update);
}

// ═══════════════════════════════════════════
// Toast Notification System
// ═══════════════════════════════════════════

function showToast(title, message, icon = '💰') {
    const container = document.getElementById('toastContainer');

    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.innerHTML = `
        <span class="toast-icon">${icon}</span>
        <div class="toast-content">
            <div class="toast-title">${title}</div>
            <div class="toast-message">${message}</div>
        </div>
    `;

    container.appendChild(toast);

    setTimeout(() => {
        toast.classList.add('leaving');
        setTimeout(() => toast.remove(), 300);
    }, 5000);
}

// ═══════════════════════════════════════════
// API Fetching & Helpers
// ═══════════════════════════════════════════

async function fetchJSON(url) {
    try {
        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return await res.json();
    } catch (err) {
        console.error(`Fetch error (${url}):`, err);
        return null;
    }
}

async function postJSON(url, body) {
    try {
        const res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        return await res.json();
    } catch (err) {
        console.error(`Post error (${url}):`, err);
        return null;
    }
}

async function putJSON(url, body) {
    try {
        const res = await fetch(url, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        return await res.json();
    } catch (err) {
        console.error(`Put error (${url}):`, err);
        return null;
    }
}

// ═══════════════════════════════════════════
// KPI Cards
// ═══════════════════════════════════════════

async function updateKPIs() {
    const data = await fetchJSON(API.summary);
    if (!data) return;

    const kpiIncome = document.getElementById('kpiIncome');
    const kpiExpense = document.getElementById('kpiExpense');
    const kpiBalance = document.getElementById('kpiBalance');
    const kpiSavings = document.getElementById('kpiSavings');

    const prevIncome = parseFloat(kpiIncome.dataset.value) || 0;
    const prevExpense = parseFloat(kpiExpense.dataset.value) || 0;
    const prevBalance = parseFloat(kpiBalance.dataset.value) || 0;
    const prevSavings = parseFloat(kpiSavings.dataset.value) || 0;

    animateValue(kpiIncome, prevIncome, data.total_income, 800, formatRupiah);
    animateValue(kpiExpense, prevExpense, data.total_expense, 800, formatRupiah);
    animateValue(kpiBalance, prevBalance, data.balance, 800, formatRupiah);
    animateValue(kpiSavings, prevSavings, data.savings_rate, 800, v => `${v.toFixed(1)}%`);

    kpiIncome.dataset.value = data.total_income;
    kpiExpense.dataset.value = data.total_expense;
    kpiBalance.dataset.value = data.balance;
    kpiSavings.dataset.value = data.savings_rate;

    document.getElementById('kpiIncomeSub').textContent = `${data.transaction_count} transaksi · ${data.period_days} hari`;
    document.getElementById('kpiBalanceSub').textContent = data.balance >= 0 ? '📈 Surplus' : '📉 Defisit';

    const savingsSub = document.getElementById('kpiSavingsSub');
    if (data.savings_rate >= 20) {
        savingsSub.textContent = '🟢 Excellent!';
    } else if (data.savings_rate >= 0) {
        savingsSub.textContent = '🟡 Bisa ditingkatkan';
    } else {
        savingsSub.textContent = '🔴 Pengeluaran > Pemasukan';
    }
}

// ═══════════════════════════════════════════
// Behavior Analysis & Recommendations
// ═══════════════════════════════════════════

async function updateBehaviorAnalysis() {
    const data = await fetchJSON(API.analysis);
    if (!data) return;

    // Recommendations List
    const recList = document.getElementById('recommendationsList');
    if (!data.recommendations || data.recommendations.length === 0) {
        recList.innerHTML = `<div class="recommendation-item info">
            <span class="recommendation-icon">💡</span>
            <div>
                <div class="recommendation-title">Belum ada analisis cukup</div>
                <div class="recommendation-desc">Catat lebih banyak transaksi di Telegram bot untuk mendapatkan rekomendasi pintar.</div>
            </div>
        </div>`;
    } else {
        recList.innerHTML = data.recommendations.map(rec => `
            <div class="recommendation-item ${rec.type}">
                <span class="recommendation-icon">${rec.icon}</span>
                <div>
                    <div class="recommendation-title">${rec.title}</div>
                    <div class="recommendation-desc">${rec.message}</div>
                </div>
            </div>
        `).join('');
    }

    // Top Categories
    const topList = document.getElementById('topCategoriesList');
    if (!data.top_categories || data.top_categories.length === 0) {
        topList.innerHTML = `<div style="color: var(--text-muted); font-size: 13px;">Belum ada pengeluaran bulan ini.</div>`;
    } else {
        topList.innerHTML = data.top_categories.map(cat => {
            const changeText = cat.change_pct > 0 ? `+${cat.change_pct}%` : `${cat.change_pct}%`;
            return `
                <div class="top-cat-item">
                    <span class="top-cat-name">${cat.category}</span>
                    <div>
                        <span class="top-cat-val">${formatRupiahFull(cat.amount)}</span>
                        <span class="top-cat-change ${cat.trend}">${changeText}</span>
                    </div>
                </div>
            `;
        }).join('');
    }
}

// ═══════════════════════════════════════════
// Trend Chart (With Period Switcher)
// ═══════════════════════════════════════════

async function updateTrendChart(period = currentPeriod) {
    currentPeriod = period;
    const data = await fetchJSON(`${API.trend}?period=${period}`);
    if (!data) return;

    const labels = data.map(d => formatDateShort(d.date));
    const expenses = data.map(d => d.expense);
    const incomes = data.map(d => d.income);

    const ctx = document.getElementById('trendChart').getContext('2d');

    if (trendChart) {
        trendChart.data.labels = labels;
        trendChart.data.datasets[0].data = expenses;
        trendChart.data.datasets[1].data = incomes;
        trendChart.update();
        return;
    }

    const expenseGradient = ctx.createLinearGradient(0, 0, 0, 280);
    expenseGradient.addColorStop(0, COLORS.expense.gradient[0]);
    expenseGradient.addColorStop(1, COLORS.expense.gradient[1]);

    const incomeGradient = ctx.createLinearGradient(0, 0, 0, 280);
    incomeGradient.addColorStop(0, COLORS.income.gradient[0]);
    incomeGradient.addColorStop(1, COLORS.income.gradient[1]);

    trendChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [
                {
                    label: 'Pengeluaran',
                    data: expenses,
                    borderColor: COLORS.expense.main,
                    backgroundColor: expenseGradient,
                    borderWidth: 2.5,
                    fill: true,
                    tension: 0.4,
                    pointRadius: 3,
                    pointHoverRadius: 6,
                },
                {
                    label: 'Pemasukan',
                    data: incomes,
                    borderColor: COLORS.income.main,
                    backgroundColor: incomeGradient,
                    borderWidth: 2.5,
                    fill: true,
                    tension: 0.4,
                    pointRadius: 3,
                    pointHoverRadius: 6,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: {
                    display: true,
                    position: 'top',
                    align: 'end',
                    labels: { boxWidth: 12, boxHeight: 12, borderRadius: 3, padding: 16 },
                },
                tooltip: {
                    backgroundColor: 'rgba(13, 13, 21, 0.95)',
                    borderColor: 'rgba(99, 102, 241, 0.2)',
                    borderWidth: 1,
                    cornerRadius: 10,
                    padding: 12,
                    callbacks: {
                        label: ctx => `${ctx.dataset.label}: ${formatRupiahFull(ctx.parsed.y)}`,
                    },
                },
            },
            scales: {
                x: { grid: { display: false } },
                y: {
                    grid: { color: 'rgba(255, 255, 255, 0.04)' },
                    ticks: { callback: v => formatRupiah(v), maxTicksLimit: 6 },
                },
            },
        },
    });
}

// ═══════════════════════════════════════════
// Category & Monthly Charts
// ═══════════════════════════════════════════

async function updateCategoryChart() {
    const data = await fetchJSON(API.categories);
    if (!data || data.length === 0) return;

    const labels = data.map(d => d.category);
    const values = data.map(d => d.total);
    const colors = data.map((_, i) => COLORS.categories[i % COLORS.categories.length]);

    const ctx = document.getElementById('categoryChart').getContext('2d');

    if (categoryChart) {
        categoryChart.data.labels = labels;
        categoryChart.data.datasets[0].data = values;
        categoryChart.data.datasets[0].backgroundColor = colors;
        categoryChart.update('none');
        return;
    }

    categoryChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels,
            datasets: [{
                data: values,
                backgroundColor: colors,
                borderColor: 'rgba(6, 6, 11, 0.8)',
                borderWidth: 3,
                hoverOffset: 8,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '65%',
            plugins: {
                legend: {
                    display: true,
                    position: 'right',
                    labels: {
                        color: '#f8fafc',
                        boxWidth: 12,
                        boxHeight: 12,
                        padding: 12,
                        font: { size: 12, family: "'Plus Jakarta Sans', sans-serif" },
                        generateLabels: (chart) => {
                            const dataset = chart.data.datasets[0];
                            const total = dataset.data.reduce((a, b) => a + b, 0);
                            return chart.data.labels.map((label, i) => ({
                                text: `${label} ${((dataset.data[i] / total) * 100).toFixed(0)}%`,
                                fillStyle: dataset.backgroundColor[i],
                                strokeStyle: 'transparent',
                                fontColor: '#f8fafc',
                                index: i,
                            }));
                        },
                    },
                },
                tooltip: {
                    callbacks: {
                        label: ctx => {
                            const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
                            const pct = ((ctx.parsed / total) * 100).toFixed(1);
                            return ` ${formatRupiahFull(ctx.parsed)} (${pct}%)`;
                        },
                    },
                },
            },
        },
    });
}

async function updateMonthlyChart() {
    const data = await fetchJSON(API.monthly);
    if (!data || data.length === 0) return;

    const labels = data.map(d => {
        const [y, m] = d.month.split('-');
        const months = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];
        return `${months[parseInt(m) - 1]} ${y.slice(2)}`;
    });
    const incomes = data.map(d => d.income);
    const expenses = data.map(d => d.expense);

    const ctx = document.getElementById('monthlyChart').getContext('2d');

    if (monthlyChart) {
        monthlyChart.data.labels = labels;
        monthlyChart.data.datasets[0].data = incomes;
        monthlyChart.data.datasets[1].data = expenses;
        monthlyChart.update('none');
        return;
    }

    monthlyChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels,
            datasets: [
                {
                    label: 'Pemasukan',
                    data: incomes,
                    backgroundColor: 'rgba(16, 185, 129, 0.7)',
                    borderRadius: 6,
                },
                {
                    label: 'Pengeluaran',
                    data: expenses,
                    backgroundColor: 'rgba(244, 63, 94, 0.7)',
                    borderRadius: 6,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { display: true, position: 'top', align: 'end' },
                tooltip: {
                    callbacks: {
                        label: ctx => `${ctx.dataset.label}: ${formatRupiahFull(ctx.parsed.y)}`,
                    },
                },
            },
            scales: {
                x: { grid: { display: false } },
                y: { grid: { color: 'rgba(255, 255, 255, 0.04)' }, ticks: { callback: v => formatRupiah(v) } },
            },
        },
    });
}

// ═══════════════════════════════════════════
// Savings Goals & Budgets Rendering
// ═══════════════════════════════════════════

async function updateSavingsGoals() {
    const data = await fetchJSON(API.savings);
    const container = document.getElementById('savingsGrid');

    if (!data || data.length === 0) {
        container.innerHTML = `<div style="color: var(--text-muted); font-size: 13px; text-align: center; padding: 20px;">
            Belum ada goal tabungan. Buat goal baru atau lewat bot (/tabung).
        </div>`;
        return;
    }

    container.innerHTML = data.map(g => `
        <div class="savings-item">
            <div class="savings-item-header">
                <span class="savings-item-title"><span>${g.icon || '🎯'}</span> ${g.name}</span>
                <span class="savings-item-values">${formatRupiah(g.current_amount)} / ${formatRupiah(g.target_amount)} (${g.progress}%)</span>
            </div>
            <div class="progress-bar-container">
                <div class="progress-bar-fill" style="width: ${Math.min(g.progress, 100)}%;"></div>
            </div>
        </div>
    `).join('');
}

async function updateBudgets() {
    const data = await fetchJSON(API.budgets);
    const container = document.getElementById('budgetList');

    if (!data || data.length === 0) {
        container.innerHTML = `<div style="color: var(--text-muted); font-size: 13px; text-align: center; padding: 20px;">
            Belum ada alokasi budget. Set budget lewat bot (/budget) atau tombol di atas.
        </div>`;
        return;
    }

    container.innerHTML = data.map(b => `
        <div class="budget-item">
            <div class="budget-item-header">
                <span class="budget-item-title">${b.category}</span>
                <span class="budget-item-pct ${b.status}">${formatRupiah(b.spent)} / ${formatRupiah(b.budget)} (${b.percentage}%)</span>
            </div>
            <div class="progress-bar-container">
                <div class="progress-bar-fill ${b.status}" style="width: ${Math.min(b.percentage, 100)}%;"></div>
            </div>
        </div>
    `).join('');
}

// ═══════════════════════════════════════════
// Transactions Table
// ═══════════════════════════════════════════

async function updateTransactions(highlight = false) {
    const data = await fetchJSON(API.transactions + '?limit=20');
    if (!data) return;

    const tbody = document.getElementById('transactionsBody');
    const emptyState = document.getElementById('emptyState');
    const txCount = document.getElementById('txCount');

    if (data.length === 0) {
        tbody.innerHTML = '';
        emptyState.style.display = 'block';
        txCount.textContent = '0 transaksi';
        return;
    }

    emptyState.style.display = 'none';
    txCount.textContent = `${data.length} transaksi`;

    const rows = data.map((tx, i) => {
        const isIncome = tx.type === 'income';
        const typeLabel = isIncome ? 'Pemasukan' : 'Pengeluaran';
        const typeIcon = isIncome ? '↗' : '↘';
        const typeClass = isIncome ? 'income' : 'expense';
        const newClass = highlight && i === 0 ? ' new-row' : '';

        // Stringify the tx object safely for the onclick handler
        const txJson = JSON.stringify(tx).replace(/"/g, '&quot;');
        
        return `
            <tr class="${newClass}">
                <td>
                    <div class="tx-date">${formatDate(tx.created_at)}</div>
                    <div class="tx-date" style="font-size: 11px; opacity: 0.6;">${formatTime(tx.created_at)}</div>
                </td>
                <td>
                    <span class="tx-type ${typeClass}">${typeIcon} ${typeLabel}</span>
                </td>
                <td>${tx.category}</td>
                <td class="hide-mobile">${tx.description || '-'}</td>
                <td style="text-align: right; white-space: nowrap;">
                    <span class="tx-amount ${typeClass}">${isIncome ? '+' : '-'} ${formatRupiahFull(tx.amount)}</span>
                    <button class="btn-icon" onclick="openEditTxModal(${txJson})" style="margin-left: 8px; background: none; border: none; cursor: pointer; opacity: 0.7;" title="Edit Transaksi">
                        ✏️
                    </button>
                    <button class="btn-icon" onclick="deleteTransaction(${tx.id})" style="margin-left: 4px; background: none; border: none; cursor: pointer; opacity: 0.7; color: inherit;" title="Hapus Transaksi">
                        🗑️
                    </button>
                </td>
            </tr>
        `;
    });

    tbody.innerHTML = rows.join('');
}

// ═══════════════════════════════════════════
// Edit Transaction Handling
// ═══════════════════════════════════════════

function openEditTxModal(tx) {
    document.getElementById('editTxId').value = tx.id;
    document.getElementById('editTxType').value = tx.type;
    document.getElementById('editTxAmount').value = tx.amount;
    document.getElementById('editTxCategory').value = tx.category || '';
    document.getElementById('editTxAccount').value = tx.account_name || '';
    document.getElementById('editTxDesc').value = tx.description || '';
    document.getElementById('editTxModal').style.display = 'flex';
}

function closeEditTxModal() {
    document.getElementById('editTxModal').style.display = 'none';
}

async function submitEditTx() {
    const id = document.getElementById('editTxId').value;
    const type = document.getElementById('editTxType').value;
    const amount = parseFloat(document.getElementById('editTxAmount').value);
    const category = document.getElementById('editTxCategory').value;
    const account = document.getElementById('editTxAccount').value;
    const desc = document.getElementById('editTxDesc').value;

    if (!amount || amount <= 0) {
        showToast('Jumlah tidak valid!', 'error');
        return;
    }

    const payload = {
        amount: amount,
        type: type,
        category: category,
        description: desc,
        account_name: account
    };

    const res = await putJSON(`/api/transactions/${id}`, payload);
    if (res) {
        showToast('Transaksi berhasil diedit!');
        closeEditTxModal();
        // The SSE will trigger the reload automatically
    } else {
        showToast('Gagal mengedit transaksi', 'error');
    }
}

// ═══════════════════════════════════════════
// Modals Handling
// ═══════════════════════════════════════════

function openSavingsModal() {
    document.getElementById('savingsModal').style.display = 'flex';
}
function closeSavingsModal() {
    document.getElementById('savingsModal').style.display = 'none';
    document.getElementById('savingsNameInput').value = '';
    document.getElementById('savingsTargetInput').value = '';
}

async function submitSavingsGoal() {
    const name = document.getElementById('savingsNameInput').value.trim();
    const target = parseFloat(document.getElementById('savingsTargetInput').value);

    if (!name || isNaN(target) || target <= 0) {
        showToast('Input Tidak Valid', 'Isi nama goal dan target nominal yang benar', '⚠️');
        return;
    }

    const res = await postJSON(API.savings, { name, target_amount: target });
    if (res && !res.error) {
        showToast('Goal Tabungan Dibuat!', `${name} — ${formatRupiahFull(target)}`, '🏦');
        closeSavingsModal();
        updateSavingsGoals();
    } else {
        showToast('Gagal Membuat Goal', res?.error || 'Terjadi kesalahan', '❌');
    }
}

function openBudgetModal() {
    document.getElementById('budgetModal').style.display = 'flex';
}
function closeBudgetModal() {
    document.getElementById('budgetModal').style.display = 'none';
    document.getElementById('budgetLimitInput').value = '';
}

async function submitBudget() {
    const category = document.getElementById('budgetCategorySelect').value;
    const limit = parseFloat(document.getElementById('budgetLimitInput').value);

    if (isNaN(limit) || limit <= 0) {
        showToast('Input Tidak Valid', 'Isi limit bulanan yang benar', '⚠️');
        return;
    }

    const res = await postJSON(API.budgets, { category, monthly_limit: limit });
    if (res && !res.error) {
        showToast('Budget Di-set!', `${category} — ${formatRupiahFull(limit)}/bln`, '💰');
        closeBudgetModal();
        updateBudgets();
        updateBehaviorAnalysis();
    } else {
        showToast('Gagal Set Budget', res?.error || 'Terjadi kesalahan', '❌');
    }
}

async function updateAccounts() {
    const data = await fetchJSON(API.accounts);
    const container = document.getElementById('accountsList');
    if (!container) return;

    if (!data || data.length === 0) {
        container.innerHTML = `<div style="color: var(--text-muted); font-size: 13px; text-align: center; padding: 20px;">
            Belum ada rekening/akun tabungan. Tambah lewat bot (/tambahakun) atau tombol di atas.
        </div>`;
        return;
    }

    container.innerHTML = data.map(acc => `
        <div class="account-item">
            <div class="account-item-header">
                <span class="account-item-title"><span>${acc.icon || '💳'}</span> ${acc.name}</span>
                <span class="account-item-val">${formatRupiahFull(acc.balance)}</span>
            </div>
        </div>
    `).join('');
}

function openAccountModal() {
    document.getElementById('accountModal').style.display = 'flex';
}
function closeAccountModal() {
    document.getElementById('accountModal').style.display = 'none';
    document.getElementById('accountNameInput').value = '';
    document.getElementById('accountBalanceInput').value = '';
}

async function submitAccount() {
    const name = document.getElementById('accountNameInput').value.trim();
    const balance = parseFloat(document.getElementById('accountBalanceInput').value);

    if (!name || isNaN(balance)) {
        showToast('Input Tidak Valid', 'Isi nama akun dan nominal saldo yang benar', '⚠️');
        return;
    }

    const res = await postJSON(API.accounts, { name, balance });
    if (res && !res.error) {
        showToast('Akun Diperbarui!', `${name} — ${formatRupiahFull(balance)}`, '🏛️');
        closeAccountModal();
        updateAccounts();
    } else {
        showToast('Gagal Simpan Akun', res?.error || 'Terjadi kesalahan', '❌');
    }
}

// ═══════════════════════════════════════════
// Server-Sent Events (Real-time Updates)
// ═══════════════════════════════════════════

function connectSSE() {
    if (sseConnection) {
        sseConnection.close();
    }

    sseConnection = new EventSource(API.sse);

    sseConnection.onopen = () => {
        const indicator = document.getElementById('liveIndicator');
        if (indicator) indicator.style.borderColor = 'rgba(16, 185, 129, 0.3)';
    };

    sseConnection.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            handleSSEEvent(data);
        } catch (err) {
            console.error('SSE parse error:', err);
        }
    };

    sseConnection.onerror = () => {
        const indicator = document.getElementById('liveIndicator');
        if (indicator) indicator.style.borderColor = 'rgba(244, 63, 94, 0.3)';

        setTimeout(() => {
            if (sseConnection.readyState === EventSource.CLOSED) {
                connectSSE();
            }
        }, 5000);
    };
}

function handleSSEEvent(data) {
    if (data.event === 'heartbeat' || data.event === 'connected') return;

    if (data.event === 'new_transaction') {
        const tx = data.transaction;
        const isIncome = tx.type === 'income';
        showToast(
            `${isIncome ? 'Pemasukan' : 'Pengeluaran'} Baru!`,
            `${tx.description} — ${formatRupiahFull(tx.amount)}`,
            isIncome ? '💵' : '💸'
        );
        refreshDashboard(true);
    } else if (data.event === 'savings_updated') {
        showToast('Tabungan Diperbarui', 'Data goal tabungan terbaru telah dimuat', '🏦');
        updateSavingsGoals();
        updateKPIs();
    } else if (data.event === 'budget_updated') {
        showToast('Budget Diperbarui', 'Konfigurasi budget terbaru dimuat', '💰');
        updateBudgets();
        updateBehaviorAnalysis();
    } else if (data.event === 'account_updated') {
        showToast('Rekening Diperbarui', 'Data rekening & simpanan telah dimuat', '🏛️');
        updateAccounts();
    } else if (data.event === 'transaction_deleted') {
        showToast('Transaksi Dihapus', 'Data dashboard diperbarui', '🗑️');
        refreshDashboard(false);
    }
}

// ═══════════════════════════════════════════
// Dashboard Refresh
// ═══════════════════════════════════════════

async function refreshDashboard(highlightNew = false) {
    await Promise.all([
        updateKPIs(),
        updateBehaviorAnalysis(),
        updateTrendChart(currentPeriod),
        updateCategoryChart(),
        updateMonthlyChart(),
        updateSavingsGoals(),
        updateBudgets(),
        updateAccounts(),
        updateTransactions(highlightNew),
    ]);
}

// ═══════════════════════════════════════════
// Initialization
// ═══════════════════════════════════════════

document.addEventListener('DOMContentLoaded', async () => {
    updateHeaderDate();
    setInterval(updateHeaderDate, 60000);

    // Setup Period Switcher buttons
    document.querySelectorAll('.period-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            document.querySelectorAll('.period-btn').forEach(b => b.classList.remove('active'));
            e.target.classList.add('active');
            updateTrendChart(e.target.dataset.period);
        });
    });

    await refreshDashboard();
    connectSSE();

    setInterval(() => refreshDashboard(false), 60000);
});



// ═══════════════════════════════════════════
// Delete Transaction Handling
// ═══════════════════════════════════════════

async function deleteTransaction(txId) {
    if (!confirm('Apakah kamu yakin ingin menghapus transaksi ini? Data yang sudah dihapus tidak bisa dikembalikan.')) {
        return;
    }

    try {
        const res = await fetch(`/api/transactions/${txId}`, {
            method: 'DELETE',
        });
        
        if (!res.ok) throw new Error('Gagal menghapus transaksi');
        
        console.log('Transaction deleted:', txId);
        
        // Reload all data to reflect changes
        refreshDashboard(false);
    } catch (err) {
        console.error('Error deleting transaction:', err);
        alert('Gagal menghapus transaksi. Silakan coba lagi.');
    }
}
