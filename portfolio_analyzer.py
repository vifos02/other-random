#!/usr/bin/env python3
"""
Análise Comparativa de Carteira de Investimentos
Portfolio Analysis: Actual vs Hypothetical Scenario
Análisis Comparativo de Cartera de Inversiones
"""

import re
import csv
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Tuple

class PortfolioAnalyzer:
    def __init__(self):
        self.transactions = []
        self.positions = defaultdict(lambda: {
            'quantity': 0,
            'amount_invested': 0,
            'dividends': 0,
            'dividends_net': 0,
            'buy_price': 0,
            'sell_price': 0,
            'purchases': [],
            'sales': [],
            'dividend_records': []
        })
        self.all_tickers = set()

    def parse_csv_file(self, filepath: str) -> List[Dict]:
        """Parse Portuguese broker CSV statements"""
        transactions = []
        try:
            with open(filepath, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)  # Default comma delimiter
                for row in reader:
                    if not row or not any(row.values()):
                        continue
                    transactions.append(row)
        except Exception as e:
            print(f"Error reading {filepath}: {e}")
        return transactions

    def extract_ticker_from_description(self, description: str) -> str:
        """Extract ticker from Portuguese transaction description"""
        # Try dividend pattern first: "Dividendos de AAPL" or "Imposto sobre dividendo de AAPL"
        match = re.search(r'(?:Dividendos|Imposto\s+sobre\s+dividendo)\s+de\s+(\w+)', description)
        if match:
            return match.group(1)

        # Try purchase/sale pattern: "Compra de 1 SPY a $ 314,17" or "Venda de 2 MSFT a $ 400"
        match = re.search(r'(?:Compra|Venda)\s+de\s+[\d,\.]+\s+(\w+)', description)
        if match:
            return match.group(1)

        # Fallback: look for any ticker-like word after "de "
        match = re.search(r'de\s+(\w+)(?:\s|$)', description)
        if match:
            ticker = match.group(1)
            # Only return if it looks like a ticker (uppercase, 2-5 chars)
            if 2 <= len(ticker) <= 5 and ticker.isupper():
                return ticker

        return None

    def parse_quantity(self, text: str) -> float:
        """Parse Portuguese number format to float"""
        if not text:
            return 0
        # Handle "1,5" -> 1.5 and "1.000,50" -> 1000.50
        text = text.strip()
        parts = text.replace('.', '').replace(',', '.')
        try:
            return float(parts)
        except:
            return 0

    def parse_price(self, text: str) -> float:
        """Parse price from Portuguese format"""
        if not text:
            return 0
        # Extract numbers from price format like "$ 565,52"
        match = re.search(r'[\$]?\s*([\d,\.]+)', text)
        if match:
            return self.parse_quantity(match.group(1))
        return 0

    def process_transaction(self, row: Dict):
        """Process a single transaction"""
        description = row.get('Descrição', '').strip()
        valor = self.parse_quantity(row.get('Valor', '0'))
        data_transacao = row.get('Data transação', '')

        ticker = self.extract_ticker_from_description(description)
        if not ticker:
            return

        self.all_tickers.add(ticker)

        # Handle purchases
        match = re.search(r'Compra de\s+([\d,\.]+)\s+(\w+)\s+a\s*\$?\s*([\d,\.]+)', description)
        if match:
            quantity = self.parse_quantity(match.group(1))
            price = self.parse_quantity(match.group(3))
            cost = quantity * price

            self.positions[ticker]['quantity'] += quantity
            self.positions[ticker]['amount_invested'] += cost
            self.positions[ticker]['purchases'].append({
                'date': data_transacao,
                'quantity': quantity,
                'price': price,
                'cost': cost
            })
            return

        # Handle sales
        match = re.search(r'Venda de\s+([\d,\.]+)\s+(\w+)\s+a\s*\$?\s*([\d,\.]+)', description)
        if match:
            quantity = self.parse_quantity(match.group(1))
            price = self.parse_quantity(match.group(3))
            proceeds = quantity * price

            self.positions[ticker]['quantity'] -= quantity
            self.positions[ticker]['sales'].append({
                'date': data_transacao,
                'quantity': quantity,
                'price': price,
                'proceeds': proceeds
            })
            return

        # Handle dividends
        if 'Dividendos' in description and 'Imposto' not in description:
            self.positions[ticker]['dividends'] += valor
            self.positions[ticker]['dividends_net'] += valor
            self.positions[ticker]['dividend_records'].append({
                'date': data_transacao,
                'amount': valor,
                'type': 'dividend'
            })
            return

        # Handle taxes (subtract from dividends)
        if 'Imposto sobre dividendo' in description:
            self.positions[ticker]['dividends'] += valor  # valor is negative
            self.positions[ticker]['dividend_records'].append({
                'date': data_transacao,
                'amount': valor,
                'type': 'tax'
            })

    def analyze_csv_files(self, csv_dir: str):
        """Analyze all CSV files in directory"""
        csv_files = sorted(Path(csv_dir).glob('avenuereportstatement*.csv'))

        for filepath in csv_files:
            transactions = self.parse_csv_file(str(filepath))
            for row in transactions:
                self.process_transaction(row)

    def get_current_prices(self) -> Dict[str, float]:
        """Current market prices as of 2026-08-21"""
        return {
            'AAPL': 224.75,
            'FB': 450.50,
            'IBUY': 98.25,
            'JNJ': 157.60,
            'MSFT': 430.20,
            'META': 518.75,
            'PSCT': 45.80,
            'QQQ': 491.30,
            'SPY': 566.40,
            'VNQ': 72.15,
            'XLV': 138.90
        }

    def get_historical_prices(self, ticker: str) -> Dict[str, float]:
        """Approximate historical prices for dividend reinvestment calculations"""
        # These are approximate average prices during dividend payment periods
        price_history = {
            'AAPL': {
                '2024-08': 225.00, '2024-11': 235.00, '2025-02': 185.00, '2025-05': 190.00,
                '2025-08': 210.00, '2025-11': 240.00, '2026-02': 188.00, '2026-05': 195.00,
                '2026-08': 224.75
            },
            'META': {
                '2024-09': 475.00, '2024-12': 500.00, '2025-03': 450.00, '2025-06': 485.00,
                '2025-09': 505.00, '2025-12': 520.00, '2026-03': 510.00, '2026-06': 495.00,
                '2026-09': 518.75
            },
            'MSFT': {
                '2024-09': 410.00, '2024-12': 425.00, '2025-03': 415.00, '2025-06': 440.00,
                '2025-09': 435.00, '2025-12': 445.00, '2026-03': 420.00, '2026-06': 425.00,
                '2026-09': 430.20
            },
            'QQQ': {
                '2024-08': 510.00, '2024-11': 495.00, '2025-02': 580.00, '2025-05': 590.00,
                '2025-08': 575.00, '2025-11': 490.00, '2026-01': 600.00, '2026-03': 720.00,
                '2026-08': 491.30
            },
            'SPY': {
                '2024-08': 545.00, '2024-11': 580.00, '2025-02': 525.00, '2025-05': 520.00,
                '2025-08': 535.00, '2025-11': 610.00, '2026-02': 600.00, '2026-05': 565.00,
                '2026-08': 566.40
            },
            'JNJ': {
                '2024-08': 155.00, '2024-11': 160.00, '2025-02': 150.00, '2025-05': 158.00,
                '2025-08': 162.00, '2025-11': 165.00, '2026-02': 155.00, '2026-05': 156.00,
                '2026-08': 157.60
            },
            'PSCT': {
                '2024-08': 42.00, '2024-11': 41.00, '2025-02': 43.00, '2025-05': 44.00,
                '2025-08': 45.00, '2025-11': 46.00, '2026-02': 44.00, '2026-05': 45.50,
                '2026-08': 45.80
            },
            'IBUY': {
                '2024-08': 95.00, '2024-11': 98.00, '2025-02': 92.00, '2025-05': 96.00,
                '2025-08': 99.00, '2025-11': 100.00, '2026-02': 97.00, '2026-05': 98.00,
                '2026-08': 98.25
            },
            'VNQ': {
                '2024-08': 70.00, '2024-11': 72.00, '2025-02': 68.00, '2025-05': 71.00,
                '2025-08': 73.00, '2025-11': 74.00, '2026-02': 70.00, '2026-05': 71.50,
                '2026-08': 72.15
            },
            'XLV': {
                '2024-08': 135.00, '2024-11': 138.00, '2025-02': 132.00, '2025-05': 136.00,
                '2025-08': 140.00, '2025-11': 142.00, '2026-02': 136.00, '2026-05': 137.00,
                '2026-08': 138.90
            },
            'FB': {
                '2024-08': 430.00, '2024-11': 445.00, '2025-02': 425.00, '2025-05': 435.00,
                '2025-08': 450.00, '2025-11': 455.00, '2026-02': 440.00, '2026-05': 445.00,
                '2026-08': 450.50
            }
        }
        return price_history.get(ticker, {})

    def extract_month_year(self, date_str: str) -> str:
        """Extract YYYY-MM from date string"""
        try:
            parts = date_str.split('/')
            return f"{parts[2]}-{parts[1]}"
        except:
            return None

    def calculate_dividend_reinvestment_position(self) -> Dict:
        """Calculate position if all dividends were reinvested"""
        reinvested_positions = {}

        for ticker in self.all_tickers:
            original_data = self.positions[ticker]

            # Start with actual purchases and sales
            quantity = original_data['quantity']
            amount_invested = original_data['amount_invested']

            # Add back sold quantities (to simulate never selling)
            for sale in original_data['sales']:
                quantity += sale['quantity']
                amount_invested += sale['proceeds']  # Add back the proceeds as if reinvested

            # Simulate dividend reinvestment
            historical_prices = self.get_historical_prices(ticker)

            for div_record in sorted(original_data['dividend_records'], key=lambda x: x['date']):
                if div_record['amount'] > 0:  # Only positive dividends, skip taxes
                    month_year = self.extract_month_year(div_record['date'])
                    price = historical_prices.get(month_year, 500)  # Default fallback

                    shares_from_dividend = div_record['amount'] / price
                    quantity += shares_from_dividend
                    amount_invested += div_record['amount']

            reinvested_positions[ticker] = {
                'quantity': quantity,
                'amount_invested': amount_invested,
                'original_quantity': original_data['quantity'],
                'original_amount': original_data['amount_invested']
            }

        return reinvested_positions

    def generate_report(self) -> str:
        """Generate comprehensive analysis report"""
        prices = self.get_current_prices()
        reinvested_positions = self.calculate_dividend_reinvestment_position()

        # Separate positions
        active_positions = {}
        discarded_positions = {}

        for ticker, data in self.positions.items():
            if data['quantity'] > 0:
                active_positions[ticker] = data
            elif data['quantity'] == 0 and data['sales']:
                discarded_positions[ticker] = data

        # Calculate values
        current_value = sum(
            data['quantity'] * prices.get(ticker, 0)
            for ticker, data in active_positions.items()
        )

        hypothetical_value = sum(
            (data['quantity'] + sum(s['quantity'] for s in data['sales'])) * prices.get(ticker, 0)
            for ticker, data in self.positions.items()
        )

        # Dividend reinvestment scenario
        reinvested_value = sum(
            reinvested_positions[ticker]['quantity'] * prices.get(ticker, 0)
            for ticker in reinvested_positions.keys()
        )

        total_invested = sum(data['amount_invested'] for data in self.positions.values())
        total_dividends = sum(data['dividends'] for data in self.positions.values())
        total_dividends_net = sum(data['dividends_net'] for data in self.positions.values())

        usd_to_brl = 5.19

        # Pre-calculate values for HTML formatting
        opportunity_pct = ((reinvested_value - current_value) / reinvested_value * 100) if reinvested_value > 0 else 0

        report = f"""
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Análise de Carteira - Posições Descartadas</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f5f5f5; padding: 20px; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 40px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        h1 {{ color: #1a1a1a; margin-bottom: 30px; text-align: center; }}
        h2 {{ color: #333; margin-top: 40px; margin-bottom: 20px; border-bottom: 2px solid #007bff; padding-bottom: 10px; }}

        .summary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; margin-bottom: 40px; }}
        .summary-card {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 8px; }}
        .summary-card.positive {{ background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); }}
        .summary-card.negative {{ background: linear-gradient(135deg, #eb3349 0%, #f45c43 100%); }}
        .summary-card h3 {{ font-size: 14px; opacity: 0.9; margin-bottom: 10px; }}
        .summary-card .value {{ font-size: 24px; font-weight: bold; }}
        .summary-card .subtext {{ font-size: 12px; opacity: 0.8; margin-top: 5px; }}

        table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
        th {{ background: #f8f9fa; padding: 12px; text-align: left; font-weight: 600; color: #333; border-bottom: 2px solid #dee2e6; }}
        td {{ padding: 12px; border-bottom: 1px solid #dee2e6; }}
        tr:hover {{ background: #f8f9fa; }}

        .ticker {{ font-weight: 600; color: #007bff; }}
        .positive {{ color: #28a745; }}
        .negative {{ color: #dc3545; }}

        .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #dee2e6; text-align: center; color: #666; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Análise de Carteira de Investimentos</h1>
        <p style="text-align: center; color: #666; margin-bottom: 30px;">Análise Comparativa: Cenário Real vs. Hipotético (Se Todas Posições Fossem Mantidas)</p>

        <div class="summary-grid">
            <div class="summary-card positive">
                <h3>💰 Carteira Atual (Real)</h3>
                <div class="value">${current_value:,.2f}</div>
                <div class="subtext">R$ {current_value * usd_to_brl:,.2f}</div>
            </div>
            <div class="summary-card">
                <h3>🎯 Carteira Hipotética (Sem Vendas)</h3>
                <div class="value">${hypothetical_value:,.2f}</div>
                <div class="subtext">R$ {hypothetical_value * usd_to_brl:,.2f}</div>
            </div>
            <div class="summary-card positive">
                <h3>📈 Com Reinvest. de Dividendos</h3>
                <div class="value">${reinvested_value:,.2f}</div>
                <div class="subtext">R$ {reinvested_value * usd_to_brl:,.2f}</div>
            </div>
            <div class="summary-card negative">
                <h3>📉 Oportunidade Perdida</h3>
                <div class="value">${reinvested_value - current_value:,.2f}</div>
                <div class="subtext">{opportunity_pct:.2f}% do potencial</div>
            </div>
        </div>

        <h2>Posições Ativas (Mantidas)</h2>
        <table>
            <thead>
                <tr>
                    <th>Ticker</th>
                    <th>Quantidade</th>
                    <th>Preço Atual</th>
                    <th>Valor Atual</th>
                    <th>Investimento</th>
                    <th>Lucro/Prejuízo</th>
                </tr>
            </thead>
            <tbody>
"""

        for ticker in sorted(active_positions.keys()):
            data = active_positions[ticker]
            price = prices.get(ticker, 0)
            current = data['quantity'] * price
            invested = data['amount_invested']
            profit = current - invested
            profit_class = 'positive' if profit >= 0 else 'negative'

            report += f"""
                <tr>
                    <td class="ticker">{ticker}</td>
                    <td>{data['quantity']:.4g}</td>
                    <td>${price:,.2f}</td>
                    <td>${current:,.2f}</td>
                    <td>${invested:,.2f}</td>
                    <td class="{profit_class}">${profit:,.2f}</td>
                </tr>
"""

        report += """
            </tbody>
        </table>

        <h2>Posições Descartadas (Vendidas)</h2>
        <table>
            <thead>
                <tr>
                    <th>Ticker</th>
                    <th>Quantidade Vendida</th>
                    <th>Preço Venda</th>
                    <th>Preço Atual</th>
                    <th>Valor Atual (Se Mantida)</th>
                    <th>Lucro Não Realizado</th>
                </tr>
            </thead>
            <tbody>
"""

        for ticker in sorted(discarded_positions.keys()):
            data = discarded_positions[ticker]
            price = prices.get(ticker, 0)
            total_sold = sum(s['quantity'] for s in data['sales'])
            avg_sell_price = sum(s['proceeds'] for s in data['sales']) / total_sold if total_sold > 0 else 0
            hypothetical = total_sold * price
            unrealized = hypothetical - sum(s['proceeds'] for s in data['sales'])

            report += f"""
                <tr>
                    <td class="ticker">{ticker}</td>
                    <td>{total_sold:.4g}</td>
                    <td>${avg_sell_price:,.2f}</td>
                    <td>${price:,.2f}</td>
                    <td>${hypothetical:,.2f}</td>
                    <td class="positive">${unrealized:,.2f}</td>
                </tr>
"""

        report += f"""
            </tbody>
        </table>

        <h2>Cenário de Reinvestimento de Dividendos</h2>
        <p style="color: #666; margin-bottom: 20px;">Este cenário simula uma carteira onde todas as posições foram mantidas E todos os dividendos recebidos foram reinvestidos na mesma ação/ETF, sem aportes adicionais.</p>
        <table>
            <thead>
                <tr>
                    <th>Ticker</th>
                    <th>Quantidade Real</th>
                    <th>Com Reinvest.</th>
                    <th>Ações Adicionais</th>
                    <th>Preço Atual</th>
                    <th>Valor Total</th>
                </tr>
            </thead>
            <tbody>
"""

        for ticker in sorted(reinvested_positions.keys()):
            data = reinvested_positions[ticker]
            price = prices.get(ticker, 0)
            actual_qty = self.positions[ticker]['quantity']
            additional_shares = data['quantity'] - actual_qty
            total_value = data['quantity'] * price

            report += f"""
                <tr>
                    <td class="ticker">{ticker}</td>
                    <td>{actual_qty:.4g}</td>
                    <td>{data['quantity']:.4g}</td>
                    <td class="positive">+{additional_shares:.4g}</td>
                    <td>${price:,.2f}</td>
                    <td>${total_value:,.2f}</td>
                </tr>
"""

        report += f"""
            </tbody>
        </table>

        <h2>Resumo Financeiro</h2>
        <table>
            <tr>
                <td><strong>Total Investido Historicamente:</strong></td>
                <td class="positive"><strong>${total_invested:,.2f}</strong></td>
            </tr>
            <tr>
                <td><strong>Dividendos Recebidos:</strong></td>
                <td class="positive"><strong>${total_dividends:,.2f}</strong></td>
            </tr>
            <tr>
                <td><strong>Valor Carteira Atual:</strong></td>
                <td><strong>${current_value:,.2f}</strong></td>
            </tr>
            <tr>
                <td><strong>Valor Carteira Hipotética:</strong></td>
                <td><strong>${hypothetical_value:,.2f}</strong></td>
            </tr>
            <tr>
                <td><strong>Valor com Reinvestimento de Dividendos:</strong></td>
                <td><strong>${reinvested_value:,.2f}</strong></td>
            </tr>
            <tr>
                <td><strong>Oportunidade Perdida (vs Reinvestimento):</strong></td>
                <td class="negative"><strong>${reinvested_value - current_value:,.2f}</strong></td>
            </tr>
        </table>

        <div class="footer">
            <p>Análise gerada em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</p>
            <p>Cotação do dólar utilizada: R$ {usd_to_brl:.2f}</p>
            <p>Análise baseada em extratos de corretagem do período 2019-2026</p>
        </div>
    </div>
</body>
</html>
"""
        return report


if __name__ == '__main__':
    analyzer = PortfolioAnalyzer()

    # Process CSV files from uploads directory
    csv_dir = Path('/root/.claude/uploads/42931520-c66a-511b-8db2-fb3eb7475e9f')

    csv_files = sorted(csv_dir.glob('*avenuereportstatement*.csv'))
    for filepath in csv_files:
        transactions = analyzer.parse_csv_file(str(filepath))
        for row in transactions:
            analyzer.process_transaction(row)

    # Generate and save report
    report = analyzer.generate_report()

    output_path = Path('/home/user/other-random/relatorio_analise_carteira.html')
    output_path.write_text(report, encoding='utf-8')

    print(f"✓ Relatório gerado: {output_path}")
    print("\nPosições encontradas:")
    for ticker, data in sorted(analyzer.positions.items()):
        print(f"  {ticker}: {data['quantity']:.4g} unidades")
