// Register Service Worker
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('./service-worker.js')
            .then(registration => {
                console.log('Service Worker registered:', registration);
            })
            .catch(error => {
                console.log('Service Worker registration failed:', error);
            });
    });
}

// PWA Install Prompt
let deferredPrompt;
const installBtn = document.getElementById('install-btn');

window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e;
    if (installBtn) installBtn.style.display = 'block';
});

if (installBtn) {
    installBtn.addEventListener('click', async () => {
        if (deferredPrompt) {
            deferredPrompt.prompt();
            const { outcome } = await deferredPrompt.userChoice;
            console.log(`User response to the install prompt: ${outcome}`);
            deferredPrompt = null;
            installBtn.style.display = 'none';
        }
    });
}

window.addEventListener('appinstalled', () => {
    console.log('PWA was installed');
    if (installBtn) installBtn.style.display = 'none';
});

// Fetch and Render Data
async function fetchData() {
    try {
        // Add cache-busting timestamp to always get fresh data
        const response = await fetch(`data.json?t=${Date.now()}`);
        if (!response.ok) throw new Error('Failed to load data');
        const data = await response.json();
        renderDashboard(data);
    } catch (error) {
        console.error('Error fetching data:', error);
        document.getElementById('last-updated').textContent = 'Error loading data. Please try again later.';
    }
}

function renderDashboard(data) {
    // Update Header Info
    document.getElementById('last-updated').textContent = `Last Updated: ${data.last_update}`;
    document.getElementById('days-remaining').textContent = data.days_remaining;

    // Render Risk Assessment
    const riskEl = document.getElementById('risk-level');
    const riskScoreEl = document.getElementById('risk-score');
    const riskCard = document.getElementById('risk-card');

    if (data.risk_assessment) {
        riskEl.textContent = data.risk_assessment.level;
        riskScoreEl.textContent = data.risk_assessment.score;
        riskCard.style.borderLeft = `5px solid ${data.risk_assessment.color}`;
        riskEl.style.color = data.risk_assessment.color;
    }

    // Render Metrics
    const metricsContainer = document.getElementById('metrics-container');
    metricsContainer.innerHTML = '';

    data.metrics.forEach(metric => {
        const card = document.createElement('div');
        card.className = 'metric-card glass';

        let statusColor = '#28a745'; // Normal
        if (metric.signal.includes('CRITICAL')) statusColor = '#dc3545';
        else if (metric.signal.includes('HIGH')) statusColor = '#fd7e14';
        else if (metric.signal.includes('RISING')) statusColor = '#ffc107';

        card.innerHTML = `
            <h3>${metric.name}</h3>
            <div class="value">${metric.value}</div>
            <div class="signal" style="color: ${statusColor}">
                <span class="dot" style="background-color: ${statusColor}"></span>
                ${metric.signal}
            </div>
            ${metric.volatility_24h ? `<div class="volatility">24h Volatility: ${metric.volatility_24h}</div>` : ''}
        `;
        metricsContainer.appendChild(card);
    });

    // Render AI Insights - Updated to use crash_analysis and news_summary
    if (data.ai_insights) {
        const crashAnalysisEl = document.getElementById('crash-analysis-content');
        const newsSummaryEl = document.getElementById('news-summary-content');

        if (crashAnalysisEl) crashAnalysisEl.innerHTML = data.ai_insights.crash_analysis || 'No data available.';
        if (newsSummaryEl) newsSummaryEl.innerHTML = data.ai_insights.news_summary || 'No data available.';
    }
}

// Initial Load
fetchData();
