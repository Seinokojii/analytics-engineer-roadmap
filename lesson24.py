"""
Den 24: BI osnovy vizualizatsii
matplotlib + seaborn + podgotovka dannykh dlya Power BI
"""

import pandas as pd
import numpy as np
import duckdb
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import seaborn as sns
from pathlib import Path

print("=" * 70)
print(" " * 15 + "DEN 24: BI OSNOVY VIZUALIZATSII")
print("=" * 70)


# ========================================
# CHAST 1: PODGOTOVKA DANNYKH IZ DBT
# ========================================

print("\n" + "=" * 70)
print("1  CHAST 1: Zagruzka dannykh iz dbt/DuckDB")
print("=" * 70)

# Podklyuchayemsya k nashey dbt baze
dbt_db_path = Path('dbt_analytics') / 'analytics.duckdb'

if dbt_db_path.exists():
    con = duckdb.connect(str(dbt_db_path), read_only=True)
    print(f"Podklyuchilis k: {dbt_db_path}")

    tables = con.execute("SHOW TABLES").df()
    print(f"Tablitsy v baze:")
    for t in tables['name'].tolist():
        n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {n} strok")

    # Zagruzka modeley
    fct_orders = con.execute("SELECT * FROM fct_orders_enriched").df()
    dim_customers = con.execute("SELECT * FROM dim_customers").df()
    con.close()
    print(f"\nfct_orders_enriched: {len(fct_orders)} strok")
    print(f"dim_customers: {len(dim_customers)} strok")

else:
    print("dbt baza ne naydena, sozdayom demo-dannyye")
    np.random.seed(42)
    N = 500
    fct_orders = pd.DataFrame({
        'order_id':     range(1, N + 1),
        'user_id':      np.random.randint(1, 101, N),
        'amount':       np.random.randint(100, 5000, N),
        'status':       np.random.choice(['completed'], N),
        'revenue_tier': np.random.choice(
            ['low', 'medium', 'high', 'vip'], N, p=[0.4, 0.35, 0.2, 0.05]
        ),
        'order_month':  np.random.randint(1, 13, N),
        'order_quarter': np.random.randint(1, 5, N),
        'order_date':   pd.date_range('2024-01-01', periods=N, freq='17H')
    })
    dim_customers = pd.DataFrame({
        'user_id':      range(1, 101),
        'user_name':    [f'User_{i}' for i in range(1, 101)],
        'city':         np.random.choice(['MOSCOW', 'SPB', 'KAZAN'], 100),
        'total_orders': np.random.randint(1, 20, 100),
        'total_spent':  np.random.randint(500, 50000, 100)
    })
    print("Demo-dannyye sozdany")


# ========================================
# CHAST 2: KPI DASHBOARD
# ========================================

print("\n" + "=" * 70)
print("2  CHAST 2: KPI - klyuchevyye metriki")
print("=" * 70)

total_revenue    = fct_orders['amount'].sum()
total_orders     = len(fct_orders)
unique_customers = fct_orders['user_id'].nunique()
avg_order        = fct_orders['amount'].mean()

print(f"""
KPI DASHBOARD:
  Obshchaya vyruchka:       {total_revenue:>12,.0f} rub
  Vsego zakazov:            {total_orders:>12,}
  Unikalnych klientov:      {unique_customers:>12,}
  Sredniy chek:             {avg_order:>12,.0f} rub
""")


# ========================================
# CHAST 3: VIZUALIZATSIYA — 4 GRAFIKA
# ========================================

print("\n" + "=" * 70)
print("3  CHAST 3: Vizualizatsiya — 4 grafika")
print("=" * 70)

Path('reports').mkdir(exist_ok=True)

fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('E-Commerce Analytics Dashboard', fontsize=16, fontweight='bold')

# --- GRAFIK 1: Vyruchka po mesyatsam ---
ax1 = axes[0, 0]
monthly = fct_orders.groupby('order_month')['amount'].sum().reset_index()
monthly.columns = ['month', 'revenue']
ax1.bar(monthly['month'], monthly['revenue'], color='steelblue', alpha=0.8)
ax1.set_title('Vyruchka po mesyatsam')
ax1.set_xlabel('Mesyats')
ax1.set_ylabel('Vyruchka (rub)')
ax1.set_xticks(range(1, 13))
for bar, val in zip(ax1.patches, monthly['revenue']):
    ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1000,
             f'{val/1000:.0f}k', ha='center', va='bottom', fontsize=8)

# --- GRAFIK 2: Распределение revenue_tier ---
ax2 = axes[0, 1]
tier_counts = fct_orders['revenue_tier'].value_counts()
colors = ['#2ecc71', '#3498db', '#e67e22', '#9b59b6', '#e74c3c']
ax2.pie(tier_counts.values, labels=tier_counts.index,
        autopct='%1.1f%%', colors=colors[:len(tier_counts)], startangle=90)
ax2.set_title('Raspredeleniye po revenue tier')

# --- GRAFIK 3: Top-10 klientov ---
ax3 = axes[1, 0]
top10 = dim_customers.nlargest(10, 'total_spent')[['user_name', 'total_spent']]
ax3.barh(top10['user_name'], top10['total_spent'], color='coral', alpha=0.8)
ax3.set_title('Top-10 klientov po vyruchke')
ax3.set_xlabel('Total spent (rub)')
ax3.invert_yaxis()

# --- GRAFIK 4: Boxplot summy zakaza po tier ---
ax4 = axes[1, 1]
tiers_order = ['low', 'medium', 'high', 'vip']
tiers_data = [fct_orders[fct_orders['revenue_tier'] == t]['amount'].values
              for t in tiers_order if t in fct_orders['revenue_tier'].values]
tiers_labels = [t for t in tiers_order
                if t in fct_orders['revenue_tier'].values]
ax4.boxplot(tiers_data, labels=tiers_labels, patch_artist=True,
            boxprops=dict(facecolor='lightblue', alpha=0.7))
ax4.set_title('Summa zakaza po tier (boxplot)')
ax4.set_xlabel('Revenue Tier')
ax4.set_ylabel('Amount (rub)')

plt.tight_layout()
plt.savefig('reports/dashboard.png', dpi=150, bbox_inches='tight')
plt.close()
print("Grafik sokhranyon: reports/dashboard.png")


# ========================================
# CHAST 4: EKSPORT DLYA POWER BI
# ========================================

print("\n" + "=" * 70)
print("4  CHAST 4: Eksport dannykh dlya Power BI")
print("=" * 70)

# Power BI chitayet CSV i Excel
fct_orders.to_csv('reports/fct_orders_for_powerbi.csv', index=False, encoding='utf-8')
dim_customers.to_csv('reports/dim_customers_for_powerbi.csv', index=False, encoding='utf-8')

# Summary dlya dashborda
summary = fct_orders.groupby('order_month').agg(
    orders=('order_id', 'count'),
    revenue=('amount', 'sum'),
    avg_check=('amount', 'mean'),
    customers=('user_id', 'nunique')
).reset_index()
summary['revenue'] = summary['revenue'].round(0)
summary['avg_check'] = summary['avg_check'].round(0)
summary.to_csv('reports/monthly_summary_for_powerbi.csv', index=False, encoding='utf-8')

print("Fayly dlya Power BI soxraneny v reports/:")
print("  fct_orders_for_powerbi.csv")
print("  dim_customers_for_powerbi.csv")
print("  monthly_summary_for_powerbi.csv")

print("""
INSTRUKTSIYA PODKLYUCHENIYA K POWER BI:
1. Skachy Power BI Desktop: https://powerbi.microsoft.com/desktop
2. Otkroy Power BI Desktop
3. Get Data → Text/CSV
4. Vyberi fct_orders_for_powerbi.csv
5. Load → OK
6. Povtori dlya dim_customers_for_powerbi.csv
7. Model View: sozdai svyaz user_id → user_id
""")


# ========================================
# CHAST 5: SEABORN — KRASIVYYE GRAFIKI
# ========================================

print("\n" + "=" * 70)
print("5  CHAST 5: Seaborn — prodvinutaya vizualizatsiya")
print("=" * 70)

fig2, axes2 = plt.subplots(1, 2, figsize=(14, 5))
fig2.suptitle('Advanced Analytics', fontsize=14, fontweight='bold')

# Heatmap: vyruchka po kvartalу i tieru
ax5 = axes2[0]
pivot = fct_orders.groupby(['order_quarter', 'revenue_tier'])['amount'].sum().unstack(fill_value=0)
sns.heatmap(pivot, annot=True, fmt='.0f', cmap='Blues', ax=ax5)
ax5.set_title('Vyruchka: Kvartal x Tier')
ax5.set_xlabel('Revenue Tier')
ax5.set_ylabel('Kvartal')

# Distribution: raspredeleniye summy zakaza
ax6 = axes2[1]
sns.histplot(fct_orders['amount'], bins=30, kde=True, ax=ax6, color='steelblue')
ax6.set_title('Raspredeleniye summy zakaza')
ax6.set_xlabel('Amount (rub)')
ax6.set_ylabel('Kolichestvo zakazov')
ax6.axvline(fct_orders['amount'].mean(), color='red', linestyle='--',
            label=f"Mean: {fct_orders['amount'].mean():.0f}")
ax6.axvline(fct_orders['amount'].median(), color='orange', linestyle='--',
            label=f"Median: {fct_orders['amount'].median():.0f}")
ax6.legend()

plt.tight_layout()
plt.savefig('reports/advanced_analytics.png', dpi=150, bbox_inches='tight')
plt.close()
print("Grafik sokhranyon: reports/advanced_analytics.png")


# ========================================
# ITOGI
# ========================================

print("\n" + "=" * 70)
print("DEN 24 ZAVERSHEN!")
print("=" * 70)
print(f"""
Ty sozdal:
1. KPI metrik iz dbt/DuckDB (revenue, orders, customers, avg_check)
2. Dashboard iz 4 grafikov → reports/dashboard.png
3. CSV eksport dlya Power BI (3 fajla v reports/)
4. Seaborn heatmap + distribution → reports/advanced_analytics.png

SLEDUYUSHCHIY SHAG:
python lesson24_bi_basics.py
Otkroy reports/dashboard.png — eto tvoy pervyy dashboard!

Sleduyushchiy den: Den 25 — Power BI zagruzka dannykh
""")