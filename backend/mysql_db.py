import os
import mysql.connector 

def get_connection():
    return mysql.connector.connect(
      host=os.getenv("MYSQL_HOST", "127.0.0.1"),
      port=int(os.getenv("MYSQL_PORT", 3306)),
      user="root",
      password="root",
      database="invoice_db"   
)   