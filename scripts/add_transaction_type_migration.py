import sqlite3

def run_migration():
    con = sqlite3.connect('saghf_database.db')
    cur = con.cursor()

    p_cols = [c[1] for c in cur.execute('PRAGMA table_info(properties)')]
    if 'transaction_type' not in p_cols:
        cur.execute('ALTER TABLE properties ADD COLUMN transaction_type VARCHAR(20)')
        print('Added transaction_type to properties table')
    cur.execute("UPDATE properties SET transaction_type = 'buy' WHERE deal_type IN ('sale', 'buy') AND (transaction_type IS NULL OR transaction_type = '')")
    cur.execute("UPDATE properties SET transaction_type = 'rent' WHERE deal_type = 'rent' AND (transaction_type IS NULL OR transaction_type = '')")

    a_cols = [c[1] for c in cur.execute('PRAGMA table_info(accessible_listings)')]
    if 'transaction_type' not in a_cols:
        cur.execute('ALTER TABLE accessible_listings ADD COLUMN transaction_type VARCHAR(20)')
        print('Added transaction_type to accessible_listings table')
    cur.execute("UPDATE accessible_listings SET transaction_type = 'buy' WHERE deal_type IN ('sale', 'buy') AND (transaction_type IS NULL OR transaction_type = '')")
    cur.execute("UPDATE accessible_listings SET transaction_type = 'rent' WHERE deal_type = 'rent' AND (transaction_type IS NULL OR transaction_type = '')")

    con.commit()
    print('Properties breakdown:', cur.execute('SELECT transaction_type, deal_type, count(*) FROM properties GROUP BY transaction_type, deal_type').fetchall())
    print('AccessibleListings breakdown:', cur.execute('SELECT transaction_type, deal_type, count(*) FROM accessible_listings GROUP BY transaction_type, deal_type').fetchall())
    con.close()

if __name__ == '__main__':
    run_migration()
