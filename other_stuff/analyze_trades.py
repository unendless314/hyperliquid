import csv
import math
import datetime
from collections import defaultdict

# Configuration
INPUT_FILE = 'trade_history.csv'
OUTPUT_FILE = 'trade_report.html'
INITIAL_CAPITAL = 3000000.0

def calculate_metrics(trades, initial_capital):
    # Prepare data containers
    equity_curve = [] # List of (timestamp, equity)
    daily_pnl = defaultdict(float)
    
    current_equity = initial_capital
    equity_curve.append((None, current_equity)) # Start point
    
    # Trading performance metrics
    close_trades = [] # Only considering 'Close' actions for Win/Loss analysis
    total_pnl = 0.0
    
    # Process trades sorted by time (assuming CSV is roughly sorted, but let's parse dates first)
    # The CSV format from user snippet: 2025/12/6 11:30:09
    parsed_trades = []
    
    for t in trades:
        try:
            dt = datetime.datetime.strptime(t['time'], '%Y/%m/%d %H:%M:%S')
            pnl = float(t['closedPnl'])
            action = t['dir']
            parsed_trades.append({
                'time': dt,
                'pnl': pnl,
                'action': action,
                'price': t['px']
            })
        except ValueError:
            continue # Skip bad lines

    # Sort by time just in case
    parsed_trades.sort(key=lambda x: x['time'])

    first_date = parsed_trades[0]['time'].date() if parsed_trades else datetime.date.today()
    last_date = parsed_trades[-1]['time'].date() if parsed_trades else datetime.date.today()

    # Iterate to build equity curve and stats
    for t in parsed_trades:
        current_equity += t['pnl']
        total_pnl += t['pnl']
        equity_curve.append((t['time'], current_equity))
        
        # Daily PnL for Sharpe
        date_key = t['time'].strftime('%Y-%m-%d')
        daily_pnl[date_key] += t['pnl']
        
        # Trade Analysis (Win Rate/Profit Factor)
        # We assume "Close" indicates a realized trade outcome.
        # "Open" usually just incurs fees (negative PnL), which affects Equity but isn't a "Loss trade" in strategy terms.
        if t['action'].startswith('Close'):
            close_trades.append(t['pnl'])

    # 1. Basic Stats
    final_equity = current_equity
    return_rate = (final_equity - initial_capital) / initial_capital * 100
    
    # 2. Win Rate & Profit Factor
    wins = [x for x in close_trades if x > 0]
    losses = [x for x in close_trades if x <= 0]
    
    total_trades_count = len(close_trades)
    win_count = len(wins)
    loss_count = len(losses)
    
    win_rate = (win_count / total_trades_count * 100) if total_trades_count > 0 else 0
    
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float('inf')

    # 3. Max Drawdown
    # We iterate through the equity curve
    max_equity = initial_capital
    max_drawdown_amount = 0.0
    max_drawdown_pct = 0.0
    
    for _, eq in equity_curve:
        if eq > max_equity:
            max_equity = eq
        
        dd_amount = max_equity - eq
        dd_pct = (dd_amount / max_equity) * 100 if max_equity > 0 else 0
        
        if dd_amount > max_drawdown_amount:
            max_drawdown_amount = dd_amount
        if dd_pct > max_drawdown_pct:
            max_drawdown_pct = dd_pct

    # 4. Sharpe Ratio
    # We need a continuous daily time series. Fill missing days with 0 PnL?
    # Better: Calculate daily equity, then daily % return based on previous day's equity.
    
    # Generate full date range
    delta = last_date - first_date
    daily_returns = []
    
    sim_equity = initial_capital
    
    for i in range(delta.days + 1):
        day = first_date + datetime.timedelta(days=i)
        d_str = day.strftime('%Y-%m-%d')
        
        # PnL for this day
        day_pnl = daily_pnl.get(d_str, 0.0)
        
        # Return for this day relative to start of day equity
        if sim_equity > 0:
            pct_ret = day_pnl / sim_equity
            daily_returns.append(pct_ret)
        else:
            daily_returns.append(0.0)
            
        sim_equity += day_pnl

    if len(daily_returns) > 1:
        avg_daily_ret = sum(daily_returns) / len(daily_returns)
        variance = sum([(x - avg_daily_ret) ** 2 for x in daily_returns]) / (len(daily_returns) - 1)
        stdev = math.sqrt(variance)
        
        # Annualized Sharpe (assuming 365 days for crypto)
        # Risk free rate = 0
        if stdev > 0:
            sharpe_ratio = (avg_daily_ret / stdev) * math.sqrt(365)
        else:
            sharpe_ratio = 0.0
    else:
        sharpe_ratio = 0.0

    return {
        'initial_capital': initial_capital,
        'final_equity': final_equity,
        'total_pnl': total_pnl,
        'return_rate': return_rate,
        'total_trades': total_trades_count,
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'max_drawdown_amount': max_drawdown_amount,
        'max_drawdown_pct': max_drawdown_pct,
        'sharpe_ratio': sharpe_ratio,
        'equity_curve': equity_curve, # List of (datetime object, float)
        'parsed_trades': parsed_trades
    }

def generate_html(metrics):
    # Prepare data for JS chart
    # Timestamps need to be ISO strings or similar for Chart.js
    labels = []
    data_points = []
    
    # Downsample if too many points for the chart to look clean, or just take all
    # Let's take every point, but format date nicely.
    # The first point is (None, Initial), let's make it the time of first trade minus a bit or just use first trade time
    
    start_time = metrics['parsed_trades'][0]['time'] if metrics['parsed_trades'] else datetime.datetime.now()
    
    # Add initial point
    labels.append((start_time - datetime.timedelta(seconds=1)).strftime('%Y-%m-%d %H:%M:%S'))
    data_points.append(metrics['initial_capital'])
    
    for t, eq in metrics['equity_curve']:
        if t is None: continue
        labels.append(t.strftime('%Y-%m-%d %H:%M:%S'))
        data_points.append(round(eq, 2))

    html = f"""
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>交易回測報告</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{ font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; background-color: #f4f4f9; color: #333; margin: 0; padding: 20px; }}
        .container {{ max-width: 1000px; margin: 0 auto; background: #fff; padding: 30px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        h1 {{ text-align: center; color: #2c3e50; margin-bottom: 30px; }}
        .metrics-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 40px; }}
        .card {{ background: #f8f9fa; padding: 20px; border-radius: 8px; text-align: center; border-left: 5px solid #3498db; }}
        .card h3 {{ margin: 0 0 10px 0; font-size: 14px; color: #7f8c8d; text-transform: uppercase; }}
        .card .value {{ font-size: 24px; font-weight: bold; color: #2c3e50; }}
        .card.positive .value {{ color: #27ae60; }}
        .card.negative .value {{ color: #e74c3c; }}
        .chart-container {{ position: relative; height: 400px; width: 100%; margin-bottom: 40px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 20px; font-size: 14px; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background-color: #f2f2f2; color: #555; }}
        tr:hover {{ background-color: #f5f5f5; }}
        .footer {{ text-align: center; margin-top: 40px; font-size: 12px; color: #aaa; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>交易績效報告</h1>
        
        <div class="metrics-grid">
            <div class="card">
                <h3>總收益 (Net PnL)</h3>
                <div class="value {'positive' if metrics['total_pnl'] >= 0 else 'negative'}">
                    ${metrics['total_pnl']:,.2f}
                </div>
            </div>
            <div class="card">
                <h3>總回報率 (ROI)</h3>
                <div class="value {'positive' if metrics['return_rate'] >= 0 else 'negative'}">
                    {metrics['return_rate']:.2f}%
                </div>
            </div>
            <div class="card">
                <h3>勝率 (Win Rate)</h3>
                <div class="value">
                    {metrics['win_rate']:.1f}%
                </div>
            </div>
            <div class="card">
                <h3>盈虧比 (Profit Factor)</h3>
                <div class="value">
                    {metrics['profit_factor']:.2f}
                </div>
            </div>
            <div class="card">
                <h3>夏普率 (Sharpe Ratio)</h3>
                <div class="value">
                    {metrics['sharpe_ratio']:.2f}
                </div>
            </div>
            <div class="card">
                <h3>最大回撤 (Max Drawdown)</h3>
                <div class="value negative">
                    {metrics['max_drawdown_pct']:.2f}%
                </div>
            </div>
            <div class="card">
                <h3>期末權益 (Final Equity)</h3>
                <div class="value">
                    ${metrics['final_equity']:,.0f}
                </div>
            </div>
             <div class="card">
                <h3>總交易次數 (Closed)</h3>
                <div class="value">
                    {metrics['total_trades']}
                </div>
            </div>
        </div>

        <div class="chart-container">
            <canvas id="equityChart"></canvas>
        </div>

        <h2>近期交易紀錄 (最近 10 筆)</h2>
        <table>
            <thead>
                <tr>
                    <th>時間</th>
                    <th>幣種</th>
                    <th>動作</th>
                    <th>價格</th>
                    <th>損益 (PnL)</th>
                </tr>
            </thead>
            <tbody>
                {''.join([f"<tr><td>{t['time']}</td><td>BTC</td><td>{t['action']}</td><td>{t['price']}</td><td style='color: {'green' if t['pnl']>=0 else 'red'}'>{t['pnl']:.2f}</td></tr>" for t in metrics['parsed_trades'][-10:]][::-1])}
            </tbody>
        </table>
        
        <div class="footer">Generated on {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
    </div>

    <script>
        const ctx = document.getElementById('equityChart').getContext('2d');
        const equityChart = new Chart(ctx, {{
            type: 'line',
            data: {{
                labels: {labels},
                datasets: [{{
                    label: '帳戶權益 (Equity)',
                    data: {data_points},
                    borderColor: '#3498db',
                    backgroundColor: 'rgba(52, 152, 219, 0.1)',
                    borderWidth: 2,
                    pointRadius: 2,
                    fill: true,
                    tension: 0.1
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                scales: {{
                    x: {{
                        ticks: {{
                            maxTicksLimit: 10,
                            maxRotation: 0
                        }}
                    }},
                    y: {{
                        beginAtZero: false
                    }}
                }},
                plugins: {{
                    legend: {{
                        display: false
                    }},
                    tooltip: {{
                        mode: 'index',
                        intersect: false,
                        callbacks: {{
                            label: function(context) {{
                                let label = context.dataset.label || '';
                                if (label) {{
                                    label += ': ';
                                }}
                                if (context.parsed.y !== null) {{
                                    label += new Intl.NumberFormat('en-US', {{ style: 'currency', currency: 'USD' }}).format(context.parsed.y);
                                }}
                                return label;
                            }}
                        }}
                    }}
                }}
            }}
        }});
    </script>
</body>
</html>
    """
    return html

def main():
    try:
        raw_trades = []
        with open(INPUT_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                raw_trades.append(row)
        
        if not raw_trades:
            print("CSV 檔案是空的或讀取失敗。")
            return

        metrics = calculate_metrics(raw_trades, INITIAL_CAPITAL)
        html_content = generate_html(metrics)
        
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            f.write(html_content)
            
        print(f"報告已成功生成：{OUTPUT_FILE}")
        print("關鍵指標：")
        print(f"總收益: ${metrics['total_pnl']:,.2f}")
        print(f"勝率: {metrics['win_rate']:.2f}%")
        print(f"夏普率: {metrics['sharpe_ratio']:.2f}")

    except Exception as e:
        print(f"發生錯誤: {str(e)}")

if __name__ == "__main__":
    main()
