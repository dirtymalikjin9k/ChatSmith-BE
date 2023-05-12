import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import os
import time
import hashlib
from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_cors import CORS
from ask import ask_ai, delete_collection
from psycopg2 import connect, extras
from os import environ

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})
os.makedirs("data", exist_ok=True)

all_urls = set()

host = environ.get('DB_HOST')
port = environ.get('DB_PORT')
dbname = environ.get('DB_NAME')
user = environ.get('DB_USER')
password = environ.get('DB_PASSWORD')

def get_connection():
    conection = connect(host=host,
                        port=port,
                        dbname=dbname,
                        user=user,
                        password=password)
    return conection

@app.post("/api/addData")
def index():
    requestInfo = request.get_json()
    print(requestInfo)
    user_email = requestInfo['user_email']
    urls_input = requestInfo["urls_input"]
    bot_id = requestInfo['bot_id']
    urls = [url.strip() for url in urls_input.split(",")]

    # Extract the root URL from the first URL
    root_url = urljoin(urls[0], "/")

    scrape_urls(urls, root_url, user_email, bot_id)
    return "Ok"


@app.post('/api/getChatIdsByEmail')
def getChatIdsByEmail():
    try:
        requestInfo = request.get_json()
        user_email = requestInfo['user_email']
        data_directory = f"data/{user_email}"
        filenames = os.listdir(data_directory)
        print(filenames)
        return filenames
    except:
        return {}


@app.post('/api/getTextNamesByEmailAndId')
def getTextNamesByEmailAndId():
    try:
        requestInfo = request.get_json()
        user_email = requestInfo['user_email']
        id = requestInfo['id']
        data_directory = f"data/{user_email}/{id}"
        filenames = os.listdir(data_directory)
        print(filenames)
        return filenames
    except:
        return {}


@app.post('/api/getTextContentByEmailAndIdAndTextName')
def getTextContentByEmailAndIdAndTextName():
    try:
        requestInfo = request.get_json()
        user_email = requestInfo['user_email']
        id = requestInfo['id']
        text_name = requestInfo['text_name']
        data_directory = f"data/{user_email}/{id}/{text_name}"
        with open(data_directory) as file:
            content = file.read()

        print(content)
        return content
    except:
        return {}


@app.post('/api/uploadTextByEmailAndId')
def uploadTextByEmailAndId():
    try:
        requestInfo = request.get_json()
        user_email = requestInfo['user_email']
        id = requestInfo['id']
        text_name = requestInfo['text_name']
        text_content = requestInfo['text_content']
        data_directory = f"data/{user_email}/{id}"

        dirs = os.path.dirname(f"{data_directory}/{text_name}.txt")
        os.makedirs(dirs, exist_ok=True)

        with open(f"{data_directory}/{text_name}.txt", "w") as f:
            # time.sleep(5)
            for line in text_content:
                try:
                    print(line)
                    f.write(line + "\n")
                except:
                    print("error")
            f.write("\n")
    except:
        return {}


def scrape_urls(urls, root_url, user_email, bot_id):
    data_directory = f"data/{user_email}/{bot_id}"
    os.makedirs(data_directory, exist_ok=True)
    unique_content = set()
    unique_urls = set()

    print(urls)

    for url in urls:
        time.sleep(5)
        print(url)
        page = requests.get(url)
        soup = BeautifulSoup(page.content, "html.parser")
        title = soup.title.string
        print(title)
        # # Remove script and style tags
        for script in soup(["script", "style"]):
            script.extract()

        # # Remove spans with empty content
        for span in soup.find_all("span"):
            if span.text.strip() == "":
                span.decompose()

        # Get the page content
        content = [elem.get_text().strip() for elem in soup.find_all(
            ['p', 'a', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'])]

        # Get all the URLs on the page
        urls_on_page = [link.get('href') for link in soup.find_all('a')]
        urls_on_page = [url for url in urls_on_page if url is not None]

        # Prepend the root URL to relative URLs
        urls_on_page = [urljoin(root_url, url) if not url.startswith(
            "http") else url for url in urls_on_page]

        # Get the path of the URL
        path = urljoin(root_url, url).replace(root_url, "").strip("/")
        if path == "":
            path = "index"
        else:
            # Replace slashes with hyphens
            path = path.replace("/", "-")

        # Create the directory if it doesn't exist
        dirs = os.path.dirname(f"{data_directory}/{path}.txt")
        os.makedirs(dirs, exist_ok=True)

        # # Write the page content and URLs to a file
        with open(f"{data_directory}/{path}.txt", "w") as f:
            f.write(f"{title}: {url}\n")
            print("content:", content)
            # time.sleep(5)
            for line in content:
                try:
                    print(line)
                    if line not in unique_content:
                        unique_content.add(line)
                        f.write(line + "\n")
                except:
                    print("error")
            f.write("URLs:\n")
            for url in urls_on_page:
                if url not in unique_urls:
                    unique_urls.add(url)
                    f.write(f"{url}\n")
            f.write("\n")


@app.post('/api/chat')
async def api_ask():
    requestInfo = request.get_json()
    print(requestInfo)
    user_email = requestInfo['user_email']
    bot_id = requestInfo['bot_id']

    data_directory = f"data//{user_email}//{bot_id}"

    query = request.json['message_text']
    print("query=", query)
    print("bot_id=", bot_id)
    response = await ask_ai(query, data_directory, user_email, bot_id)
    app.logger.debug(f"Query: {query}")
    app.logger.debug(f"Response: {response}")
    print("response:", response)
    return jsonify({'response': response})


@app.post('/api/chatsDelete')
def api_chats_delte():
    requestInfo = request.get_json()
    print(requestInfo)
    user_email = requestInfo['user_email']
    bot_id = requestInfo['bot_id']
    response = delete_collection(user_email, bot_id)
    return response

@app.post('/api/auth/register')
def api_auth_register():
    print('----register----')
    requestInfo = request.get_json()
    email = requestInfo['user_email']
    password = requestInfo['user_password']
    if email == '' or password == '':
        return {}
    else:
        connection = get_connection()
        cursor = connection.cursor(cursor_factory=extras.RealDictCursor)

        try:
            hash_password = create_hash(password)
            cursor.execute('INSERT INTO users(email,password) VALUES (%s, %s) RETURNING *',
                        (email, hash_password))
            new_created_user = cursor.fetchone()
            print(new_created_user)

            connection.commit()
            cursor.close()
            connection.close()

            return "ok"
        except Exception as e:
            print('Error: '+ str(e))
            return "Email already exist"

@app.post('/api/auth/login')
def api_auth_login():
    requestInfo = request.get_json()
    email = requestInfo['user_email']
    password = requestInfo['user_password']
    if email == '' or password == '':
        return {}
    else:
        connection = get_connection()
        cursor = connection.cursor(cursor_factory=extras.RealDictCursor)

        try:
            hash_password = create_hash(password)
            print(hash_password)
            print(email)
            cursor.execute('SELECT * FROM users WHERE email = %s AND password = %s', (email,hash_password))
            user = cursor.fetchone()

            connection.commit()
            cursor.close()
            connection.close()

            
            if user is None:
                print(user)
                return jsonify({'message': 'Email or Password does not correct'}), 404
            return "Login Success"
        except:
            return jsonify({'message': 'Email or Password does not correct'}), 404

def create_hash(text):
    return hashlib.md5(text.encode()).hexdigest()

if __name__ == "__main__":
    app.run(debug=True, threaded=True)
