connection = connect(host=host,
                        port=port,
                        dbname=dbname,
                        user=user,
                        password=password)

cursor = connection.cursor()


query = """
    CREATE TABLE chats (
        id SERIAL PRIMARY KEY,
        email VARCHAR(150) NOT NULL,
        instance_name VARCHAR(150) NOT NULL,
        urls TEXT NOT NULL,
        bot_prompt TEXT,
        custom_text TEXT,
        bot_id INTEGER NOT NULL,
        chats JSONB NOT NULL,
        complete BOOL NOT NULL,
        created date DEFAULT CURRENT_TIMESTAMP
    )
"""

cursor.execute(query)

connection.commit()
cursor.close()
connection.close()

query = """
    CREATE TABLE subscription (
        id SERIAL PRIMARY KEY,
        email VARCHAR(150) NOT NULL,
        customer_id VARCHAR(150) NOT NULL,
        start_date VARCHAR(150) NOT NULL,
        end_date VARCHAR(150) NOT NULL,
        created date DEFAULT CURRENT_TIMESTAMP
    )
"""

query = """
    CREATE TABLE users (
        id SERIAL PRIMARY KEY,
        email VARCHAR(150) NOT NULL UNIQUE,
        password VARCHAR(150) NOT NULL,
        created date DEFAULT CURRENT_TIMESTAMP
    )
"""