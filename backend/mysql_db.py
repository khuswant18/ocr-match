import os
import mysql.connector


def get_connection():
    return mysql.connector.connect(
        host=os.environ.get("MYSQL_HOST", "mysql"),
        port=int(os.environ.get("MYSQL_PORT", 3306)),
        user="root",
        password="root",
        database="invoice_db",
    )   