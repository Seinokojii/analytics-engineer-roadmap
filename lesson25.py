"""
Den 25: Power BI — zagruzka dannykh i pervyy dashboard
Podgotovka CSV, DAX-formuly, instruktsii po sozdaniyu dashborda
"""

import pandas as pd
import numpy as np
import duckdb
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from pathlib import Path

print("=" * 70)
print(" " * 8 + "DEN 25: POWER BI — PERVYY DASHBOARD")
print("=" * 70)


# ========================================
# CHAST 1: PODGOTOVKA DANNYKH
# ========================================

print("\n" + "=" * 70)
print("1  CHAST 1: Podgotovka dannykh dlya Power BI")
print("=" * 70)

Path('reports').mkdir(exist_ok=True)

# Podklyuchayemsya k dbt baze ili sozdayom demo
dbt_db_path = Path('dbt_analytics') / 'analytics.duckdb'

if dbt_db_path.exists():
    con = duckdb.connect(str(dbt_db_path), read_only=True)
    fct_orders    = con.execute("SELECT * FROM fct_orders_enriched").df()
    dim_customers = con.execute("SELECT * FROM dim_customers").df()
    con.close()
    print(f"Dannyye iz dbt: {len(fct_orders)} zakazov, {len(dim_customers)} klientov")
else:
    np.random.seed(42)
    N = 500
    fct_orders = pd.DataFrame({
        'order_id':      range(1, N + 1),
        'user_id':       np.random.randint(1, 101, N),
        'amount':        np.random.randint(100, 5000, N),
        'status':        'completed',
        'revenue_tier':  np.random.choice(
            ['low', 'medium', 'high', 'vip'], N, p=[0.4, 0.35, 0.2, 0.05]
        ),
        'order_month':   np.random.randint(1, 13, N),
        'order_quarter': np.random.randint(1, 5, N),
        'order_date':    pd.date_range('2024-01-01', periods=N, freq='17H')
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
# CHAST 2: OPTIMIZATSIYA CSV DLYA POWER BI
# ========================================

print("\n" + "=" * 70)
print("2  CHAST 2: Optimizatsiya CSV dlya Power BI")
print("=" * 70)

# fct_orders — dobavit poleznye kolonki
fct_export = fct_orders.copy()
if 'order_date' in fct_export.columns:
    fct_export['order_date'] = pd.to_datetime(fct_export['order_date'])
    fct_export['year']           = fct_export['order_date'].dt.year
    fct_export['month_num']      = fct_export['order_date'].dt.month
    fct_export['month_name']     = fct_export['order_date'].dt.strftime('%b')
    fct_export['quarter']        = fct_export['order_date'].dt.quarter
    fct_export['day_of_week']    = fct_export['order_date'].dt.day_name()
    fct_export['week_of_year']   = fct_export['order_date'].dt.isocalendar().week.astype(int)

# dim_customers — dobavit segment
def customer_segment(spent):
    if spent >= 30000: return 'VIP'
    elif spent >= 10000: return 'Regular'
    else: return 'New'

dim_export = dim_customers.copy()
dim_export['segment'] = dim_export['total_spent'].apply(customer_segment)

# dim_date — otdelnyy kalendar (luchshaya praktika Power BI)
dates = pd.date_range('2024-01-01', '2024-12-31', freq='D')
dim_date = pd.DataFrame({
    'date':         dates,
    'year':         dates.year,
    'quarter':      dates.quarter,
    'month_num':    dates.month,
    'month_name':   dates.strftime('%B'),
    'month_short':  dates.strftime('%b'),
    'week':         dates.isocalendar().week.values,
    'day_of_week':  dates.day_name(),
    'is_weekend':   dates.dayofweek >= 5,
    'quarter_label': ['Q' + str(q) for q in dates.quarter]
})

# Sokhranit vse CSV
fct_export.to_csv('reports/fct_orders_powerbi.csv', index=False, encoding='utf-8')
dim_export.to_csv('reports/dim_customers_powerbi.csv', index=False, encoding='utf-8')
dim_date.to_csv('reports/dim_date_powerbi.csv', index=False, encoding='utf-8')

print("Sozdany 3 CSV fajla dlya Power BI:")
print(f"  fct_orders_powerbi.csv:    {len(fct_export)} strok, {len(fct_export.columns)} kolonok")
print(f"  dim_customers_powerbi.csv: {len(dim_export)} strok")
print(f"  dim_date_powerbi.csv:      {len(dim_date)} strok (365 dney)")


# ========================================
# CHAST 3: DAX FORMULY
# ========================================

print("\n" + "=" * 70)
print("3  CHAST 3: DAX-formuly dlya Power BI")
print("=" * 70)

# Sokhranim DAX-formuly v fajl dlya spravki
dax_formulas = """
============================================================
DAX FORMULY DLYA POWER BI DASHBORDA
============================================================

--- OSNOVNYYE MERY (Measures) ---

// Obshchaya vyruchka
Total Revenue =
SUM(fct_orders_powerbi[amount])

// Kolichestvo zakazov
Total Orders =
COUNTROWS(fct_orders_powerbi)

// Unikalnyye klienty
Unique Customers =
DISTINCTCOUNT(fct_orders_powerbi[user_id])

// Sredniy chek
Avg Order Value =
DIVIDE(
    SUM(fct_orders_powerbi[amount]),
    COUNTROWS(fct_orders_powerbi),
    0
)

--- FILTRY I CALCULATE ---

// Vyruchka tolko VIP
VIP Revenue =
CALCULATE(
    SUM(fct_orders_powerbi[amount]),
    fct_orders_powerbi[revenue_tier] = "vip"
)

// Zakazov za tekushchiy mesyats
Orders This Month =
CALCULATE(
    COUNTROWS(fct_orders_powerbi),
    MONTH(fct_orders_powerbi[order_date]) = MONTH(TODAY())
)

--- VYCHISLYAYEMYYE KOLONKI (Calculated Columns) ---

// Segment klienta
Customer Segment =
IF(
    dim_customers_powerbi[total_spent] >= 30000, "VIP",
    IF(
        dim_customers_powerbi[total_spent] >= 10000, "Regular",
        "New"
    )
)

// Rang klienta po vyruchke
Customer Rank =
RANKX(
    ALL(dim_customers_powerbi),
    dim_customers_powerbi[total_spent],
    ,
    DESC
)

--- % OT ITOGA ---

// Dolya vyruchki ot obshchego
Revenue Share % =
DIVIDE(
    SUM(fct_orders_powerbi[amount]),
    CALCULATE(SUM(fct_orders_powerbi[amount]), ALL(fct_orders_powerbi)),
    0
) * 100

============================================================
"""

with open('reports/dax_formulas.txt', 'w', encoding='utf-8') as f:
    f.write(dax_formulas)

print("DAX-formuly sokhraneny: reports/dax_formulas.txt")
print("""
Klyuchevyye DAX mery:
  Total Revenue      = SUM(fct_orders[amount])
  Total Orders       = COUNTROWS(fct_orders)
  Unique Customers   = DISTINCTCOUNT(fct_orders[user_id])
  Avg Order Value    = DIVIDE(SUM(...), COUNTROWS(...), 0)
  VIP Revenue        = CALCULATE(SUM(...), tier="vip")
""")


# ========================================
# CHAST 4: MAKETY DASHBORDA (PYTHON)
# ========================================

print("\n" + "=" * 70)
print("4  CHAST 4: Makety — kak budet vyglyadet dashboard")
print("=" * 70)

# Schitaem KPI
total_revenue    = fct_export['amount'].sum()
total_orders     = len(fct_export)
unique_customers = fct_export['user_id'].nunique()
avg_order        = fct_export['amount'].mean()

fig = plt.figure(figsize=(16, 10))
fig.suptitle('Power BI Dashboard Mockup — E-Commerce 2024',
             fontsize=16, fontweight='bold', y=0.98)

gs = fig.add_gridspec(3, 4, hspace=0.4, wspace=0.35)

# --- KPI Kartochki (verkhnyaya stroka) ---
kpi_data = [
    ('Total Revenue',    f'{total_revenue:,.0f} rub', '#2ecc71'),
    ('Total Orders',     f'{total_orders:,}',          '#3498db'),
    ('Unique Customers', f'{unique_customers:,}',       '#9b59b6'),
    ('Avg Order Value',  f'{avg_order:,.0f} rub',      '#e67e22'),
]

for i, (title, value, color) in enumerate(kpi_data):
    ax = fig.add_subplot(gs[0, i])
    ax.add_patch(mpatches.FancyBboxPatch(
        (0.05, 0.1), 0.9, 0.8, boxstyle="round,pad=0.05",
        facecolor=color, alpha=0.15, edgecolor=color, linewidth=2
    ))
    ax.text(0.5, 0.65, value, ha='center', va='center',
            fontsize=14, fontweight='bold', color=color,
            transform=ax.transAxes)
    ax.text(0.5, 0.25, title, ha='center', va='center',
            fontsize=9, color='gray', transform=ax.transAxes)
    ax.axis('off')

# --- Grafik 1: Vyruchka po mesyatsam (nizhnyaya levaya polovina) ---
ax2 = fig.add_subplot(gs[1:, :2])
monthly = fct_export.groupby('month_num')['amount'].sum()
ax2.plot(monthly.index, monthly.values, marker='o',
         color='steelblue', linewidth=2.5, markersize=6)
ax2.fill_between(monthly.index, monthly.values, alpha=0.15, color='steelblue')
ax2.set_title('Vyruchka po mesyatsam', fontweight='bold')
ax2.set_xlabel('Mesyats')
ax2.set_ylabel('Vyruchka (rub)')
ax2.set_xticks(range(1, 13))
ax2.grid(True, alpha=0.3)

# --- Grafik 2: Tier pie (nizhnyaya pravaya) ---
ax3 = fig.add_subplot(gs[1, 2:])
tier_counts = fct_export['revenue_tier'].value_counts()
colors_pie = ['#2ecc71', '#3498db', '#e67e22', '#9b59b6']
ax3.pie(tier_counts.values, labels=tier_counts.index,
        autopct='%1.1f%%', colors=colors_pie[:len(tier_counts)],
        startangle=90, textprops={'fontsize': 9})
ax3.set_title('Revenue Tier', fontweight='bold')

# --- Grafik 3: Top-5 gorodov (pravyy nizhniy) ---
ax4 = fig.add_subplot(gs[2, 2:])
city_rev = dim_export.groupby('city')['total_spent'].sum().sort_values(ascending=True)
ax4.barh(city_rev.index, city_rev.values, color='coral', alpha=0.8)
ax4.set_title('Vyruchka po gorodam', fontweight='bold')
ax4.set_xlabel('Total Spent (rub)')

plt.savefig('reports/powerbi_mockup.png', dpi=150, bbox_inches='tight')
plt.close()
print("Maket dashborda sokhranyon: reports/powerbi_mockup.png")


# ========================================
# CHAST 5: INSTRUKTSIYA POWER BI DESKTOP
# ========================================

print("\n" + "=" * 70)
print("5  CHAST 5: Poshagovaya instruktsiya Power BI Desktop")
print("=" * 70)

instruction = """
INSTRUKTSIYA: Pervyy dashboard v Power BI Desktop
==================================================

SHAG 1: Ustanovka
  Skachat: https://powerbi.microsoft.com/ru-ru/desktop/
  Ustanovit, otkryt Power BI Desktop

SHAG 2: Zagruzka dannykh
  Home → Get Data → Text/CSV
  Vyberi: reports/fct_orders_powerbi.csv → Load
  Eshche raz Get Data → vyberi: reports/dim_customers_powerbi.csv → Load
  Eshche raz Get Data → vyberi: reports/dim_date_powerbi.csv → Load

SHAG 3: Svyazi (Model View)
  Klikni na ikonku "Model" sleva
  Peretyashchi user_id iz fct_orders na user_id v dim_customers
    → svyaz many-to-one (mnogo zakazov → odin klient)
  Peretyashchi order_date iz fct_orders na date v dim_date
    → svyaz many-to-one

SHAG 4: DAX Mery
  Vyberi tablitsu fct_orders_powerbi v Fields
  New Measure → vvedi:
    Total Revenue = SUM(fct_orders_powerbi[amount])
  Eshche New Measure:
    Total Orders = COUNTROWS(fct_orders_powerbi)
  Eshche:
    Avg Check = DIVIDE([Total Revenue], [Total Orders], 0)

SHAG 5: Vizualizatsii
  Vyberi "Card" vizualizatsiyu
    → v Fields peretyashchi [Total Revenue]
    → peretyashchi eshche odnu kartochku: [Total Orders]
    → eshche odnu: [Avg Check]
  Vyberi "Line Chart":
    → Axis: month_num
    → Values: [Total Revenue]
  Vyberi "Pie Chart":
    → Legend: revenue_tier
    → Values: [Total Revenue]

SHAG 6: Filtr po gorodu
  Vyberi "Slicer":
    → Field: dim_customers_powerbi[city]
  Teper klikaya na gorod — vse grafiki filtruutsya!

SHAG 7: Skhranit
  File → Save As → dashboard_ecommerce.pbix
"""

with open('reports/powerbi_instruction.txt', 'w', encoding='utf-8') as f:
    f.write(instruction)

print(instruction)


# ========================================
# ITOGI
# ========================================

print("\n" + "=" * 70)
print("DEN 25 ZAVERSHEN!")
print("=" * 70)
print(f"""
Ty sozdal:
1. 3 optimizirovannyye CSV dlya Power BI (s dim_date)
2. DAX-formuly v reports/dax_formulas.txt
3. Maket dashborda → reports/powerbi_mockup.png
4. Poshagovuyu instruktsiyu → reports/powerbi_instruction.txt

TEPER OTKROY POWER BI DESKTOP I SLEDUY INSTRUKTSII!

Fajly v reports/:
  fct_orders_powerbi.csv
  dim_customers_powerbi.csv
  dim_date_powerbi.csv
  dax_formulas.txt
  powerbi_instruction.txt
  powerbi_mockup.png

Sleduyushchiy den: Den 26 — Power BI uglubleniye (3 vizualizatsii)
""")