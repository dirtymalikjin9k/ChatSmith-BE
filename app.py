import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import os
import time
import hashlib
from flask import Flask, render_template, request, redirect, url_for, jsonify, send_from_directory
from flask_cors import CORS
from ask import ask_ai, delete_data_collection, delete_collection
from psycopg2 import connect, extras
from os import environ
import json
import shutil
import stripe
import datetime
from dateutil.relativedelta import relativedelta


app = Flask(__name__, static_folder='build')
# CORS(app, resources={r"/api/*": {"origins": "https://1a78-65-109-52-221.ngrok-free.app/"}})

os.makedirs("data", exist_ok=True)

stripe.api_key = 'pk_test_51N8ikXCRd8rWbf0guJ5xqIR6c1Ya13PexdGenYTrru60C7nVLWrLxgX61ZAe55cDf53JmMKlurnS0Fb3GvIhIbfq00Su2SqotR'


# endpoint_secret = 'whsec_ef236d754b0c2badbd37c064994eddfa7a630c790b8407b1395cd8727f4fee6a'
endpoint_secret = 'whsec_aL0kutS9p1MkhhKXN8GkTnHoz7WnPXfj'

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

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Origin, X-Requested-With, Content-Type, Accept')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE')
    return response

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

def scrape_urls(urls, root_url, user_email, bot_id):
    user_email_hash = create_hash(user_email)
    print(user_email_hash)
    data_directory = f"data/{user_email_hash}/{bot_id}"
    os.makedirs(data_directory, exist_ok=True)
    unique_content = set()
    unique_urls = set()

    print(urls)

    for url in urls:
        try:
            time.sleep(5)
            print(url)
            page = requests.get(url)
            soup = BeautifulSoup(page.content, "html.parser")
            title = soup.title.string
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
            print("root = ",root_url)
            print("url = ",url + '/')
            path = urljoin(root_url, url + '/').replace(root_url, "").strip("/")
            print("path = ", path)
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
        except:
            return 

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
    response = delete_data_collection(user_email, bot_id)
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
            return "ok"


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
            print("user-------", user)
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
    instance_name = requestInfo['instace_name']
    chat_name = requestInfo['chat_name']
    prompt = requestInfo['prompt']
    bot_id = requestInfo['bot_id']
    urls_input = requestInfo['urls_input']
    chats = [{
        "question": "",
        "answer": ""
    }]

    print("urls_input = ", urls_input)
    # Extract the root URL from the first URL

    if email == '' or prompt == '' or bot_id == '' or urls_input== '' :
        return {}
    else:
        connection = get_connection()
        cursor = connection.cursor(cursor_factory=extras.RealDictCursor)
        try:
            chats_str = json.dumps(chats)
            cursor.execute('INSERT INTO chats (email, instance_name, chat_name, prompt, urls, bot_id, chats, complete) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING *',
                        (email, instance_name, chat_name, prompt, urls_input, bot_id, chats_str, 'false'))
            new_created_chat = cursor.fetchone()
            connection.commit()
            print(new_created_chat)

            cursor.execute('SELECT * FROM subscription where email = %s', (email ,))
            subscription = cursor.fetchone()
            connection.commit()

            urls = [url.strip() for url in urls_input.split(",")]

            if(subscription is None):
                urls = urls[:2]
            else: 
                end_time = datetime.datetime.fromtimestamp(int(subscription['end_date']))
                current_time = datetime.datetime.now()
                
                if(current_time > end_time):
                    urls = urls[:2]

            print(len(urls))
            root_url = urljoin(urls[0], "/")
            scrape_urls(urls, root_url, email, bot_id)

            cursor.execute('UPDATE chats SET complete = %s WHERE email = %s AND bot_id = %s', ('true', email, bot_id))
            # new_created_chat = cursor.fetchone()

            connection.commit()
            cursor.close()
            connection.close()

            return "ok"
        except Exception as e:
            print('Error: '+ str(e))
            return "can not save new chats" 

@app.post('/api/updateChat')
def api_updateChat():
    requestInfo = request.get_json()
    email = requestInfo['user_email']
    instance_name = requestInfo['instance_name']
    chat_name = requestInfo['chat_name']
    prompt = requestInfo['prompt']
    bot_id = requestInfo['bot_id']
    urls_input = requestInfo['urls_input']
    custom_text = requestInfo['custom_text']
    if email == '' or instance_name == '' or prompt == '' or bot_id == '' or urls_input== '' :
        return {}
    else:
        user_email_hash = create_hash(email)
        print(user_email_hash)
        data_directory = f"data/{user_email_hash}/{bot_id}"
        shutil.rmtree(data_directory)
        connection = get_connection()
        cursor = connection.cursor(cursor_factory=extras.RealDictCursor)
        try:
            cursor.execute("UPDATE chats SET instance_name = %s, chat_name = %s, prompt = %s, urls = %s, custom_text = %s, complete = %s WHERE email = %s AND bot_id = %s",
                    (instance_name, chat_name, prompt, urls_input, custom_text, 'false', email, bot_id))
            connection.commit()


            urls = [url.strip() for url in urls_input.split(",")]
            root_url = urljoin(urls[0], "/")
            scrape_urls(urls, root_url, email, bot_id)
            if custom_text != "":
                filename = f"{data_directory}/custom_text.txt"
                with open(filename, "w") as file:
                    file.write(custom_text)
            response = delete_data_collection(email, bot_id)
            cursor.execute("UPDATE chats SET instance_name = %s, chat_name = %s, prompt = %s, urls = %s, custom_text = %s, complete = %s WHERE email = %s AND bot_id = %s",
                    (instance_name, chat_name, prompt, urls_input, custom_text, 'false', email, bot_id))

            cursor.close()
            connection.close()

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
            print("chats = ", chats)
            connection.commit()
            cursor.close()
            connection.close()
            if len(chats) > 0:
                return jsonify({'chats': chats})
            else:
                return jsonify({'message': 'chat does not exist'}), 404 
        except Exception as e:
            print('Error: '+ str(e))
            return jsonify({'message': 'chat does not exist'}), 404
 
@app.post('/api/webhook')
def api_webhook():
    event = None
    payload = request.data
    print("endpoint_secret = ",endpoint_secret)
    if endpoint_secret:
        sig_header = request.headers.get('Stripe-Signature')
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, endpoint_secret
            )
        except stripe.error.SignatureVerificationError as e:
            print('⚠️  Webhook signature verification failed.' + str(e))
            return jsonify(success=False)
        
    # Handle the event
     # Handle the event
    charge = session = invoice = None
    if event['type'] == 'checkout.session.completed':
      session = event['data']['object']
      print("session = ",session)
    elif event['type'] == 'charge.succeeded':
      charge = event['data']['object']
      print("charge = ",charge)
    elif event['type'] == 'invoice.paid':
      invoice = event['data']['object']
      print("invoice = ",invoice)
    # ... handle other event types
    else:
      print('Unhandled event type {}'.format(event['type']))

    if charge : 
        connection = get_connection()
        cursor = connection.cursor(cursor_factory=extras.RealDictCursor)

        email = charge['billing_details']['email']

        payment_method = charge['payment_method']

        if(charge['amount'] == 2000):
            type = 2
        else:
            type = 1

        start_date = charge['created']

        date_obj = datetime.datetime.utcfromtimestamp(start_date)

        end_date_obj = date_obj + relativedelta(months=1)

        end_date = int(end_date_obj.timestamp())
        
        cursor.execute('INSERT INTO subscription(email, payment_method, type, start_date, end_date) VALUES (%s, %s, %s, %s, %s) RETURNING *',
                    (email, payment_method, type, start_date, end_date))
        new_created_user = cursor.fetchone()
        print(new_created_user)

        connection.commit()
        cursor.close()
        connection.close()

    return jsonify(success=True)

@app.post('/api/getSubscription')
def api_getSubscription():
    requestInfo = request.get_json()
    email = requestInfo['user_email']
    if email == '':
        return "ok"
    else:
        connection = get_connection()
        cursor = connection.cursor(cursor_factory=extras.RealDictCursor)
        # try:
        cursor.execute('SELECT * FROM subscription WHERE email = %s ', (email,))

        selects = cursor.fetchall()
        connection.commit()

        print(selects)
        
        if(len(selects) == 0) :
            return '1'
        else:
            subscription = selects[len(selects)-1]
            print("subscription = ", subscription)
            end_time = datetime.datetime.fromtimestamp(int(subscription['end_date']))
            current_time = datetime.datetime.now()
            
            if end_time > current_time:
                if subscription['type'] == 1:
                    cursor.close()
                    connection.close()
                    return '5'
                else: 
                    cursor.close()
                    connection.close()
                    return '10'
            else:
                cursor.execute('DELETE FROM subscription WHERE email = %s ',
                                (email, ))            
                connection.commit()
                
                cursor.execute('DELETE FROM chats WHERE email = %s ',
                                (email, ))            
                connection.commit()

                cursor.close()
                connection.close()
                return '1'

@app.post('/api/unSubscribe')
def api_unsubscribe():
    requestInfo = request.get_json()
    email = requestInfo['user_email']
    if email == '':
        return "ok"
    else:
        data_directory = f"data/{create_hash(email)}"
        shutil.rmtree(data_directory)
        connection = get_connection()
        cursor = connection.cursor(cursor_factory=extras.RealDictCursor)
        # try:
        cursor.execute('DELETE FROM subscription WHERE email = %s',
                                (email,))            
        connection.commit()

        # cursor.execute('DELETE FROM chats WHERE email = %s',
        #                         (email,))            
        # connection.commit()
        response = delete_collection(email, connection, cursor)
        cursor.close()
        connection.close()
        return "ok"

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
    app.run(host='0.0.0.0', port=3000,debug=True, threaded=True)