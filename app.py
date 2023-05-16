import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import os
import time
import hashlib
from flask import Flask, render_template, request, redirect, url_for, jsonify, send_from_directory
from flask_cors import CORS
from ask import ask_ai, delete_collection
from psycopg2 import connect, extras
from os import environ
import json
import shutil


app = Flask(__name__, static_folder='build')
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
    user_email_hash = create_hash(user_email)
    print(user_email_hash)
    data_directory = f"data/{user_email_hash}/{bot_id}"
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
    
    user_email_hash = create_hash(user_email)
    print(user_email_hash)
    data_directory = f"data//{user_email_hash}//{bot_id}"

    query = request.json['message_text']
    print("query=", query)
    print("bot_id=", bot_id)
    print('data_directory = ', data_directory)
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

@app.post('/api/botDelete')
def api_bot_delete():
    requestInfo = request.get_json()
    print(requestInfo)
    email = requestInfo['user_email']
    bot_id = requestInfo['bot_id']
    if email == '' or bot_id == '':
        return {}
    else:
        try:
            connection = get_connection()
            cursor = connection.cursor(cursor_factory=extras.RealDictCursor)
            cursor.execute('DELETE FROM chats WHERE email = %s AND bot_id = %s',
                                (email, bot_id))            
            connection.commit()
            cursor.close()
            connection.close()
            user_email_hash = create_hash(email)
            data_directory = f"data/{user_email_hash}/{bot_id}"
            shutil.rmtree(data_directory)
            return "ok"
        except Exception as e:
            print('Error: ' + str(e))


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
            return user
        except:
            return jsonify({'message': 'Email or Password does not correct'}), 404

@app.post('/api/newChat')
def api_newChat():
    requestInfo = request.get_json()
    email = requestInfo['user_email']
    chat_name = requestInfo['chat_name']
    prompt = requestInfo['prompt']
    bot_id = requestInfo['bot_id']
    urls_input = requestInfo['urls_input']
    chats = [{
        "question": "",
        "answer": ""
    }]

    # Extract the root URL from the first URL

    if email == '' or prompt == '' or bot_id == '' or urls_input== '' :
        return {}
    else:
        connection = get_connection()
        cursor = connection.cursor(cursor_factory=extras.RealDictCursor)
        try:
            chats_str = json.dumps(chats)
            cursor.execute('INSERT INTO chats (email, chat_name, prompt, urls, bot_id, chats) VALUES (%s, %s, %s, %s, %s, %s) RETURNING *',
                        (email, chat_name, prompt, urls_input, bot_id, chats_str))
            new_created_chat = cursor.fetchone()
            print(new_created_chat)
            
            connection.commit()
            cursor.close()
            connection.close()
            urls = [url.strip() for url in urls_input.split(",")]
            root_url = urljoin(urls[0], "/")
            scrape_urls(urls, root_url, email, bot_id)
            return "ok"
        except Exception as e:
            print('Error: '+ str(e))
            return "can not save new chats" 

@app.post('/api/updateChat')
def api_updateChat():
    requestInfo = request.get_json()
    email = requestInfo['user_email']
    chat_name = requestInfo['chat_name']
    prompt = requestInfo['prompt']
    bot_id = requestInfo['bot_id']
    urls_input = requestInfo['urls_input']
    custom_text = requestInfo['custom_text']
    if email == '' or prompt == '' or bot_id == '' or urls_input== '' :
        return {}
    else:
        user_email_hash = create_hash(email)
        print(user_email_hash)
        data_directory = f"data/{user_email_hash}/{bot_id}"
        shutil.rmtree(data_directory)
        connection = get_connection()
        cursor = connection.cursor(cursor_factory=extras.RealDictCursor)
        try:
            cursor.execute("UPDATE chats SET chat_name = %s, prompt = %s, urls = %s, custom_text = %s WHERE email = %s AND bot_id = %s",
                    (chat_name, prompt, urls_input, custom_text, email, bot_id))
            
            connection.commit()
            cursor.close()
            connection.close()
            urls = [url.strip() for url in urls_input.split(",")]
            root_url = urljoin(urls[0], "/")
            scrape_urls(urls, root_url, email, bot_id)
            if custom_text != "":
                filename = f"{data_directory}/custom_text.txt"
                with open(filename, "w") as file:
                    file.write(custom_text)
            return "ok"
        except Exception as e:
            print('Error: '+ str(e))
            return "can not save new chats" 

@app.post('/api/getChatInfos')
def api_getChatInfos():
    requestInfo = request.get_json()
    email = requestInfo['user_email']
    print("email = ",email)
    if email == "":
        return jsonify({'message': 'email does not exist'}), 404
    else: 
        connection = get_connection()
        cursor = connection.cursor(cursor_factory=extras.RealDictCursor)

        try:
            cursor.execute('SELECT * FROM chats WHERE email = %s ', (email,))
            chats = cursor.fetchall()

            connection.commit()
            cursor.close()
            connection.close()
            return chats
        except Exception as e:
            print('Error: '+ str(e))
            return jsonify({'message': 'chat does not exist'}), 404
    

def create_hash(text):
    return hashlib.md5(text.encode()).hexdigest()

# Serve REACT static files
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    if path != "" and os.path.exists(app.static_folder + '/' + path):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory(app.static_folder, 'index.html')

if __name__ == "__main__":
    app.run(debug=True, threaded=True)