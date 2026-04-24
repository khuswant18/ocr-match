import mysql.connector 

def get_connection():
    return mysql.connector.connect(
      host="mysql",
      port=3306,
      user="root",
      password="root",
      database="invoice_db"   
)   