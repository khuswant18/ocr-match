import mysql.connector
import os

def get_connection():
    try:
        conn = mysql.connector.connect(
            host=os.getenv("MYSQL_HOST", "127.0.0.1"), 
            port=3306,           
            user="root",
            password="root",
            database="invoice_db"
        )
        return conn
    except mysql.connector.Error as err:
        print("Error connecting to MySQL:", err)
        return None 