import pymysql

connection = pymysql.connect(
    host="127.0.0.1",
    port=3306,
    user="synth",
    password="synthpw",
    database="synth"
)

try:
    with connection.cursor() as cursor:
        cursor.execute("SELECT VERSION();")
        version = cursor.fetchone()
        print("MariaDB version:", version)

finally:
    connection.close()