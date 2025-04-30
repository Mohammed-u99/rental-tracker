import sqlite3
import pandas as pd
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
import streamlit as st

# --- Database Setup ---
conn = sqlite3.connect('rentals.db', check_same_thread=False)
c = conn.cursor()
# Tenants table with optional end_date for removals
c.execute('''
CREATE TABLE IF NOT EXISTS tenants (
    id INTEGER PRIMARY KEY,
    unit TEXT,
    name TEXT,
    phone TEXT,
    start_date TEXT,
    end_date TEXT,
    rent REAL,
    frequency TEXT,
    type TEXT
)
''')
# Payments table
c.execute('''
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER,
    due_date TEXT,
    amount_due REAL,
    amount_paid REAL,
    payment_date TEXT,
    method TEXT,
    FOREIGN KEY(tenant_id) REFERENCES tenants(id)
)
''')
conn.commit()

# Frequency to months map
freq_map = {
    'Monthly': 1,
    'Quarterly': 3,
    'Semi-Annual': 6,
    'Annual': 12
}

# Utils functions

def get_due_dates(start: date, freq_months: int, until: date) -> list[date]:
    dates = []
    current = start
    while current <= until:
        dates.append(current)
        current += relativedelta(months=freq_months)
    return dates


def calculate_status(tenant_row) -> tuple[float, str]:
    tid, unit, name, phone, start_str, end_str, rent, freq, ttype = tenant_row
    start = datetime.strptime(start_str, '%Y-%m-%d').date()
    today = date.today()
    freq_m = freq_map.get(freq, 1)

    # Generate expected due dates up to today
    due_dates = get_due_dates(start, freq_m, today)
    expected_count = len(due_dates)
    expected_amount = expected_count * rent
    # Sum payments
    c.execute('SELECT SUM(amount_paid) FROM payments WHERE tenant_id=?', (tid,))
    paid = c.fetchone()[0] or 0.0
    balance = expected_amount - paid

    # Determine status
    if balance <= 0:
        status = 'Paid'
    else:
        if any(d < today for d in due_dates):
            status = 'Overdue'
        else:
            next_due = start + relativedelta(months=freq_m * expected_count)
            if (next_due - today).days <= 7:
                status = 'Due Soon'
            else:
                status = 'Unpaid'
    return balance, status

# --- Streamlit App ---
st.set_page_config(page_title='Rental Tracker', layout='wide')
st.title('🏠 Rental Payment Tracker')

# Sidebar: Manage tenants and payments
st.sidebar.header('Manage Tenants/Payments')
mode = st.sidebar.selectbox('Action', ['Add Tenant', 'Remove Tenant', 'Add Payment'])

if mode == 'Add Tenant':
    st.sidebar.subheader('Add New Tenant')
    unit = st.sidebar.text_input('Unit/Shop Number')
    name = st.sidebar.text_input('Tenant Name')
    phone = st.sidebar.text_input('Phone Number')
    start_date = st.sidebar.date_input('Contract Start Date')
    rent = st.sidebar.number_input('Rent Amount', min_value=0.0)
    freq = st.sidebar.selectbox('Payment Frequency', list(freq_map.keys()))
    ttype = st.sidebar.selectbox('Type', ['Residential', 'Commercial'])
    if st.sidebar.button('Add'):
        c.execute(
            'INSERT INTO tenants (unit,name,phone,start_date,end_date,rent,frequency,type) VALUES (?,?,?,?,?,?,?,?)',
            (unit, name, phone, start_date.isoformat(), None, rent, freq, ttype)
        )
        conn.commit()
        st.sidebar.success(f'Tenant {name} added.')

elif mode == 'Remove Tenant':
    st.sidebar.subheader('Remove Tenant')
    c.execute('SELECT id, unit, name FROM tenants WHERE end_date IS NULL')
    active = c.fetchall()
    sel = st.sidebar.selectbox('Select Tenant', [f"{u} - {n}" for _,u,n in active])
    if st.sidebar.button('Remove'):
        tid = [tid for tid, u, n in active if f"{u} - {n}" == sel][0]
        today_str = date.today().isoformat()
        c.execute('UPDATE tenants SET end_date=? WHERE id=?', (today_str, tid))
        conn.commit()
        st.sidebar.success('Tenant removed.')

else:
    st.sidebar.subheader('Record a Payment')
    c.execute('SELECT id, unit, name FROM tenants WHERE end_date IS NULL')
    tenants_active = c.fetchall()
    sel = st.sidebar.selectbox('Select Tenant', [f"{tid}: {u} - {n}" for tid,u,n in tenants_active])
    amount_paid = st.sidebar.number_input('Amount Paid', min_value=0.0)
    pay_date = st.sidebar.date_input('Payment Date')
    method = st.sidebar.selectbox('Method', ['Cash', 'Bank Transfer'])
    if st.sidebar.button('Add Payment'):
        tid = int(sel.split(':')[0])
        due_date = pay_date.isoformat()
        c.execute(
            'INSERT INTO payments (tenant_id,due_date,amount_due,amount_paid,payment_date,method) VALUES (?,?,?,?,?,?)',
            (tid, due_date, amount_paid, amount_paid, pay_date.isoformat(), method)
        )
        conn.commit()
        st.sidebar.success('Payment recorded.')

# Main: Summary Table
st.header('Summary of Active Tenants')
c.execute('SELECT * FROM tenants WHERE end_date IS NULL')
tenants_active = c.fetchall()
rows = []
for tr in tenants_active:
    balance, status = calculate_status(tr)
    tid, unit, name, phone, start_str, _, rent_amt, freq, ttype = tr
    rows.append({
        'Unit': unit,
        'Tenant': name,
        'Rent': rent_amt,
        'Amount Due': balance,
        'Phone': phone,
        'Status': status
    })
df = pd.DataFrame(rows)
def color_status(val):
    if val == 'Overdue':
        return 'background-color: red; color: white'
    elif val == 'Due Soon':
        return 'background-color: yellow; color: black'
    elif val == 'Paid':
        return 'background-color: green; color: white'
    else:
        return ''
st.dataframe(df.style.applymap(color_status, subset=['Status']), use_container_width=True)

# Detail view
st.header('Detailed Payment Records')
sel_unit = st.selectbox('Select Unit/Shop', [tr[1] for tr in tenants_active])
if sel_unit:
    tid = [tr[0] for tr in tenants_active if tr[1] == sel_unit][0]
    c.execute('SELECT due_date, amount_due, amount_paid, payment_date, method FROM payments WHERE tenant_id=?', (tid,))
    payments = c.fetchall()
    if payments:
        df_pay = pd.DataFrame(payments, columns=['Due Date', 'Amount Due', 'Amount Paid', 'Payment Date', 'Method'])
        st.table(df_pay)
    else:
        st.info('No payment records for this tenant yet.')
