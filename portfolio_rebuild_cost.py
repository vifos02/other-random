#!/usr/bin/env python3
"""
Calculate the cost to rebuild the portfolio at current prices
with all dividends reinvested but no additional contributions
"""

from portfolio_analyzer import PortfolioAnalyzer
from pathlib import Path

analyzer = PortfolioAnalyzer()

# Parse all CSV files
csv_dir = Path('/root/.claude/uploads/42931520-c66a-511b-8db2-fb3eb7475e9f')
csv_files = sorted(csv_dir.glob('*avenuereportstatement*.csv'))

for filepath in csv_files:
    transactions = analyzer.parse_csv_file(str(filepath))
    for row in transactions:
        analyzer.process_transaction(row)

# Get reinvested positions and current prices
reinvested_positions = analyzer.calculate_dividend_reinvestment_position()
current_prices = analyzer.get_current_prices()

print("=" * 80)
print("CUSTO PARA REMONTAR A CARTEIRA (COM DIVIDENDOS REINVESTIDOS)")
print("Preços atuais em 21/08/2026")
print("=" * 80)

total_cost_usd = 0
total_cost_brl = 0
usd_to_brl = 5.19

print(f"\n{'Ticker':<8} {'Quantidade':<15} {'Preço Atual':<15} {'Custo USD':<15} {'Custo BRL':<15}")
print("-" * 80)

for ticker in sorted(reinvested_positions.keys()):
    data = reinvested_positions[ticker]
    quantity = data['quantity']
    price = current_prices.get(ticker, 0)
    cost_usd = quantity * price
    cost_brl = cost_usd * usd_to_brl

    total_cost_usd += cost_usd
    total_cost_brl += cost_brl

    print(f"{ticker:<8} {quantity:>13.4f} {price:>14,.2f} {cost_usd:>14,.2f} {cost_brl:>14,.2f}")

print("-" * 80)
print(f"{'TOTAL':<8} {'':<15} {'':<15} {total_cost_usd:>14,.2f} {total_cost_brl:>14,.2f}")
print("=" * 80)

# Comparison with current portfolio
current_positions = {}
for ticker, data in analyzer.positions.items():
    if data['quantity'] > 0:
        current_positions[ticker] = data

current_value_usd = sum(
    data['quantity'] * current_prices.get(ticker, 0)
    for ticker, data in current_positions.items()
)
current_value_brl = current_value_usd * usd_to_brl

additional_investment_usd = total_cost_usd - current_value_usd
additional_investment_brl = additional_investment_usd * usd_to_brl

print(f"\nCOMPARATIVO:")
print(f"  Carteira Atual (Real):           ${current_value_usd:>12,.2f} | R$ {current_value_brl:>12,.2f}")
print(f"  Custo para Remontar (+ Divid.): ${total_cost_usd:>12,.2f} | R$ {total_cost_brl:>12,.2f}")
print(f"  Investimento Adicional Necessário: ${additional_investment_usd:>12,.2f} | R$ {additional_investment_brl:>12,.2f}")
print(f"  Aumento Percentual: {(additional_investment_usd / current_value_usd * 100):.2f}%")
print("=" * 80)

# Show which positions would need to be added/increased
print("\nPOSIÇÕES QUE PRECISARIAM SER ADICIONADAS/AUMENTADAS:")
print(f"{'Ticker':<8} {'Atual':<12} {'Com Divid.':<12} {'Diferença':<12} {'Custo Diferença':<15}")
print("-" * 80)

for ticker in sorted(reinvested_positions.keys()):
    reinvested_qty = reinvested_positions[ticker]['quantity']
    actual_qty = analyzer.positions[ticker]['quantity']
    difference = reinvested_qty - actual_qty
    price = current_prices.get(ticker, 0)
    cost_diff = difference * price

    print(f"{ticker:<8} {actual_qty:>10.4f} {reinvested_qty:>10.4f} {difference:>10.4f} ${cost_diff:>13,.2f}")

print("=" * 80)
