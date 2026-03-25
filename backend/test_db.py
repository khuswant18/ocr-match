from db2.db_connection import get_connection

conn = get_connection()

if conn:
    print("✅ Connected to MySQL!")

    cursor = conn.cursor()
    # cursor.execute("SHOW TABLES")
    po_number = "4010510"

    cursor.execute("""
        SELECT * 
        FROM po_lines   
        WHERE po_number = %s
    """, (po_number,))
    po_data = cursor.fetchall()
    print(po_data)
    # GRN
    cursor.execute("""
        SELECT *
        FROM pol_grn
        WHERE po_trans_no = %s
    """, (int(po_number),)) 

    grn_data = cursor.fetchall()
    print("grn_data",grn_data)  

    conn.close()
else:
    print("❌ Connection failed") 