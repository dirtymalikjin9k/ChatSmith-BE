from bs4 import BeautifulSoup
from urllib.parse import urljoin
import os
import time
import hashlib
from flask import Flask, render_template, request, redirect, url_for, jsonify, send_from_directory
from flask_cors import CORS
from ask import delete_data_collection, delete_collection
from psycopg2 import connect, extras
from os import environ
import json
import shutil
import stripe
from datetime import datetime, timedelta
from google.oauth2 import id_token
from google.auth.transport import requests
from dateutil.relativedelta import relativedelta
import jwt
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
import re

from dotenv import load_dotenv

from langchain.embeddings import OpenAIEmbeddings
from langchain.vectorstores import Chroma
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.document_loaders import PyPDFLoader, TextLoader
from langchain.chains import ConversationalRetrievalChain
from langchain.document_loaders import DirectoryLoader
from langchain.chat_models import ChatOpenAI
from langchain.callbacks import get_openai_callback
from langchain.memory import ConversationBufferMemory

app = Flask(__name__, static_folder='build')

load_dotenv()

if environ.get('OPENAI_API_KEY') is not None:
    os.environ["OPENAI_API_KEY"] = environ.get('OPENAI_API_KEY')

CORS(app, resources={r"/api/*": {"origins": "*"}})

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
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'}
            page = requests.get(url, headers=headers)
            print("page =", page)
            soup = BeautifulSoup(page.content, "html.parser")
            title = soup.title.string
            print("title = ", title)
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
        except Exception as e:
            print("error:",str(e))
            return 
    return 

@app.post('/api/chat')
async def api_ask():
    requestInfo = request.get_json()
    auth_email = requestInfo['email']
    bot_id = requestInfo['bot_id']
    headers = request.headers
    bearer = headers.get('Authorization')

    try:
        token = bearer.split()[1]
        decoded = jwt.decode(token, 'chatsavvy_secret', algorithms="HS256")

        email = decoded['email']

        if(email != auth_email):
            return jsonify({'message': 'Authrization is faild'}), 404

        user_email_hash = create_hash(email)
        print(user_email_hash)
        data_directory = f"data//{user_email_hash}//{bot_id}"

        query = request.json['message_text']
        print("query=", query)
        print("bot_id=", bot_id)
        print('data_directory = ', data_directory)
        loader = DirectoryLoader(data_directory, glob="./*.txt", loader_cls=TextLoader)
        documents = loader.load()
        print("documents = ", documents)

        embeddings = OpenAIEmbeddings()
        vectorstore = Chroma.from_documents(documents, embeddings)
        print("embedding = ",embeddings)
        memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)
        retriever_openai = vectorstore.as_retriever(search_kwargs={"k": 3})
        #create the chain/Screen Shot 2023-05-26 at 9.58.31 AM.png
        llm = ChatOpenAI(model_name='gpt-3.5-turbo', temperature=0.2) 
        qa = ConversationalRetrievalChain.from_llm(llm, retriever_openai, memory=memory)
        print("qa = ", qa)
        #test a message and log cost of API call

        with get_openai_callback() as cb:
            result = qa({"question": query})
            print(cb)

        print(result)

        print(result['answer'])

        text = result['answer']

        # Check if the response contains a link
        url_pattern = re.compile(r"(?P<url>https?://[^\s]+)")

        # replace URLs with anchor tags in the text
        response = url_pattern.sub(
            r"<a href='\g<url>' target='_blank' style='color: #0000FF'>\g<url></a>", text)

        newMessage = {
            "question": query,
            "answer": response
        }

        connection = get_connection()
        cur = connection.cursor(cursor_factory=extras.RealDictCursor)
        cur.execute(
            'SELECT * FROM chats WHERE email = %s AND bot_id = %s', (email, bot_id))
        chat = cur.fetchone()
        chat_content = chat['chats']
        chat_content.append(newMessage)
        print(chat_content)
        updated_json_data_string = json.dumps(chat_content)
        cur.execute("UPDATE chats SET chats = %s WHERE email = %s AND bot_id = %s",
                    (updated_json_data_string, email, bot_id))
        connection.commit()
        cur.close()
        connection.close()

        app.logger.debug(f"Query: {query}")
        app.logger.debug(f"Response: {response}")
        print("response:", response)
        return jsonify({'message': response}), 200
    except Exception as e:
        print('Error: '+ str(e))
        return jsonify({'message': 'Bad Request'}), 404

@app.post('/api/chatsDelete')
def api_chats_delte():
    requestInfo = request.get_json()
    print(requestInfo)
    auth_email = requestInfo['email']
    bot_id = requestInfo['bot_id']
    headers = request.headers
    bearer = headers.get('Authorization')
    try:
        token = bearer.split()[1]
        decoded = jwt.decode(token, 'chatsavvy_secret', algorithms="HS256")

        email = decoded['email']

        if(email != auth_email):
            return jsonify({'message': 'Authrization is faild'}), 404
        response = delete_data_collection(auth_email, bot_id)
        if response:
            return jsonify({'message': 'Delete Success'}), 200
        else:
            return jsonify({'message': 'bad request'}), 404
    except Exception as e:
        print('Error: ' + str(e))
        return jsonify({'message': 'bad request'}), 404

@app.post('/api/botDelete')
def api_bot_delete():
    requestInfo = request.get_json()
    print(requestInfo)
    auth_email = requestInfo['email']
    bot_id = requestInfo['bot_id']
    headers = request.headers
    bearer = headers.get('Authorization')
    try:
        token = bearer.split()[1]
        decoded = jwt.decode(token, 'chatsavvy_secret', algorithms="HS256")

        email = decoded['email']

        if(email != auth_email):
            return jsonify({'message': 'Authrization is faild'}), 404

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
        return jsonify({'message': 'Chatbot Deleted'}), 200
    except Exception as e:
        print('Error: ' + str(e))
        return jsonify({'message': 'bad request'}), 404

def verify_google_token(token):
    # Specify the client ID of the Google API Console project that the credential is from
    CLIENT_ID = '241041186069-6655bsntan86u6hhf4h7t6897o2i4pn8.apps.googleusercontent.com'

    try:
        # Verify and decode the token
        decoded_token = id_token.verify_oauth2_token(token, requests.Request(), CLIENT_ID)

        # Extract information from the decoded token
        user_id = decoded_token['sub']
        user_email = decoded_token['email']
        user_name = decoded_token['name']
        print("email == ", user_email)
        # Return a dictionary containing the user information
        return {
            'id': user_id,
            'email': user_email,
            'name': user_name
        }
    except Exception as e:
        print("error:", str(e))
        # Handle invalid token error
        return None
    
@app.post('/api/auth/googleLogin')
def api_auth_googleLogin():
    requestInfo = request.get_json()
    email = requestInfo['email']
    credential = requestInfo['credential']

    print("email = ", email)
    print("credential = ", credential)

    try:
        responsePayload = verify_google_token(credential)
        print("responseEmail = ",responsePayload['email'])
        if responsePayload['email'] != email:
                return jsonify({'message': 'Bad request'}), 404
        connection = get_connection()
        cursor = connection.cursor(cursor_factory=extras.RealDictCursor)

        cursor.execute('SELECT * FROM users WHERE email = %s', (email, ))
        user = cursor.fetchone()

        if user is not None:
            payload = {
            'email': email
            }
            token = jwt.encode(payload, 'chatsavvy_secret', algorithm='HS256')
            return jsonify({'token': 'Bearer: '+token, 'email': email}), 200
    
        cursor.execute('INSERT INTO users(email) VALUES (%s) RETURNING *',
                (email,))
        new_created_user = cursor.fetchone()
        print(new_created_user)

        connection.commit()
        cursor.close()
        connection.close()

        payload = {
            'email': email
        }
        token = jwt.encode(payload, 'chatsavvy_secret', algorithm='HS256')
        
        return jsonify({'token': 'Bearer: '+token, 'email': email}), 200

    except Exception as e:
        print("error:", str(e))
        return jsonify({'message': 'Bad request'}), 404

@app.post('/api/newChat')
def api_newChat():
    requestInfo = request.get_json()
    auth_email = requestInfo['email']
    instance_name = requestInfo['instace_name']
    bot_id = requestInfo['bot_id']
    urls_input = requestInfo['urls_input']
    chats = [{
        "question": "",
        "answer": ""
    }]

    print("urls_input = ", urls_input)

    headers = request.headers
    bearer = headers.get('Authorization')
    try:
        token = bearer.split()[1]
        decoded = jwt.decode(token, 'chatsavvy_secret', algorithms="HS256")

        email = decoded['email']

        if(email != auth_email):
            return jsonify({'message': 'Authrization is faild'}), 404

        connection = get_connection()
        cursor = connection.cursor(cursor_factory=extras.RealDictCursor)
        chats_str = json.dumps(chats)
        cursor.execute('INSERT INTO chats (email, instance_name, urls, bot_id, chats, complete) VALUES (%s, %s, %s, %s, %s, %s) RETURNING *',
                    (email, instance_name, urls_input, bot_id, chats_str, 'false'))
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

        return jsonify({'message': 'Success Create'}), 200
    except Exception as e:
        print('Error: '+ str(e))
        return jsonify({'message': 'Bad Request'}), 404

@app.post('/api/updateChat')
def api_updateChat():
    requestInfo = request.get_json()
    auth_email = requestInfo['email']
    instance_name = requestInfo['instance_name']
    bot_id = requestInfo['bot_id']
    urls_input = requestInfo['urls_input']
    custom_text = requestInfo['custom_text']
    headers = request.headers
    bearer = headers.get('Authorization')
    print("bearer = ", bearer)
    try:
        token = bearer.split()[1]
        decoded = jwt.decode(token, 'chatsavvy_secret', algorithms="HS256")

        email = decoded['email']

        if(email != auth_email):
            return jsonify({'message': 'Authrization is faild'}), 404
    
        user_email_hash = create_hash(email)
        print(user_email_hash)
        data_directory = f"data/{user_email_hash}/{bot_id}"
        shutil.rmtree(data_directory)
        connection = get_connection()
        cursor = connection.cursor(cursor_factory=extras.RealDictCursor)
        cursor.execute("UPDATE chats SET instance_name = %s, urls = %s, custom_text = %s, complete = %s WHERE email = %s AND bot_id = %s",
                (instance_name, urls_input, custom_text, 'false', email, bot_id))
        connection.commit()


        urls = [url.strip() for url in urls_input.split(",")]
        root_url = urljoin(urls[0], "/")
        scrape_urls(urls, root_url, email, bot_id)
        if custom_text != "":
            filename = f"{data_directory}/custom_text.txt"
            with open(filename, "w") as file:
                file.write(custom_text)
        response = delete_data_collection(email, bot_id)
        cursor.execute("UPDATE chats SET instance_name = %s, urls = %s, custom_text = %s, complete = %s WHERE email = %s AND bot_id = %s",
                (instance_name, urls_input, custom_text, 'true', email, bot_id))
        connection.commit()
        cursor.close()
        connection.close()

        return jsonify({'message': 'Update Success'}), 404
    except Exception as e:
        print('Error: '+ str(e))
        return jsonify({'message': 'Bad Request'}), 404

@app.post('/api/getChatInfos')
def api_getChatInfos():
    requestInfo = request.get_json()
    auth_email = requestInfo['email']
    headers = request.headers
    bearer = headers.get('Authorization')
    print("bearer = ", bearer)
    try:
        token = bearer.split()[1]
        decoded = jwt.decode(token, 'chatsavvy_secret', algorithms="HS256")

        email = decoded['email']

        if(email != auth_email):
            return jsonify({'message': 'Authrization is faild'}), 404
        connection = get_connection()
        cursor = connection.cursor(cursor_factory=extras.RealDictCursor)

        try:
            cursor.execute('SELECT * FROM chats WHERE email = %s ', (email,))
            chats = cursor.fetchall()
            print("chats = ", chats)
            connection.commit()
            cursor.close()
            connection.close()
    
            return jsonify({'chats': chats})
        except Exception as e:
            print('Error: '+ str(e))
            return jsonify({'message': 'chat does not exist'}), 404
    except Exception as e:
        print('Error: '+ str(e))
        return jsonify({'message': 'bad request'}), 404

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
    # print("event-----",event)
    charge = session = invoice = customer = None
    if event['type'] == 'customer.created':
      customer  = event['data']['object']
      print("customer  = ",customer )
    elif event['type'] == 'checkout.session.completed':
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

    print("Webhook event recognized:", event['type'])

    if invoice : 
        connection = get_connection()
        cursor = connection.cursor(cursor_factory=extras.RealDictCursor)

        email = invoice['customer_email']
        print("email = ", email)
        customer_id = invoice['customer']
        print("customer_id = ", customer_id)
        start_date = invoice['created']

        date_obj = datetime.datetime.utcfromtimestamp(start_date)

        end_date_obj = date_obj + relativedelta(months=1)

        end_date = int(end_date_obj.timestamp())
        
        cursor.execute('INSERT INTO subscription(email, customer_id, start_date, end_date) VALUES (%s, %s, %s, %s) RETURNING *',
                    (email, customer_id, start_date, end_date))
        new_created_user = cursor.fetchone()
        print(new_created_user)

        connection.commit()
        cursor.close()
        connection.close()

    return jsonify(success=True)

@app.post('/api/getSubscription')
def api_getSubscription():
    requestInfo = request.get_json()
    auth_email = requestInfo['email']
    headers = request.headers
    bearer = headers.get('Authorization')
    try:
        token = bearer.split()[1]
        decoded = jwt.decode(token, 'chatsavvy_secret', algorithms="HS256")

        email = decoded['email']

        if(email != auth_email):
            return jsonify({'message': 'Authrization is faild'}), 404
        
        connection = get_connection()
        cursor = connection.cursor(cursor_factory=extras.RealDictCursor)
        # try:
        cursor.execute('SELECT * FROM subscription WHERE email = %s ', (email,))

        selects = cursor.fetchall()
        connection.commit()

        print(selects)
        
        if(len(selects) == 0) :
             return jsonify({'customerId': '','count':'1'})
        else:
            subscription = selects[len(selects)-1]
            print("subscription = ", subscription)
            end_time = datetime.datetime.fromtimestamp(int(subscription['end_date']))
            current_time = datetime.datetime.now()
            
            if end_time > current_time:
                return jsonify({'customerId': subscription['customer_id'],'count':'10'})
            else:
                cursor.execute('DELETE FROM subscription WHERE email = %s ',
                                (email, ))            
                connection.commit()
                
                cursor.execute('DELETE FROM chats WHERE email = %s ',
                                (email, ))            
                connection.commit()

                cursor.close()
                connection.close()
                return jsonify({'customerId': subscription['customer_id'],'count':'1'})
    except Exception as e:
        print('Error: '+ str(e))
        return jsonify({'message': 'bad request'}), 404

@app.post('/api/unSubscribe')
def api_unsubscribe():
    requestInfo = request.get_json()
    email = requestInfo['email']
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

@app.post('/api/sendVerifyEmail')
def api_sendVerifyEmail():
    requestInfo = request.get_json()
    email = requestInfo['email']

    # Set an expiration time of 24 hours from now
    expiry_time = datetime.utcnow() + timedelta(hours=1)

    payload = {
            'email': email,
            'expired_time': expiry_time.isoformat()
        }
    token = jwt.encode(payload, 'chatsavvy_secret', algorithm='HS256')
    print("token = ", token)
    message = Mail(
        from_email='admin@beyondreach.ai',
        to_emails=email,
        subject='Sign in to Chatsavvy',
        html_content = f'<p style="color: #500050;">Hello<br/><br/>We received a request to sign in to Beyondreach using this email address {email}. If you want to sign in to your BeyondReach account, click this link:<br/><br/><a href="https://app.chatsavvy.ai/#/verify/{token}">Sign in to BeyondReach</a><br/><br/>If you did not request this link, you can safely ignore this email.<br/><br/>Thanks.<br/><br/>Your Beyondreach team.</p>'
    )
    try:
        sg = SendGridAPIClient(api_key=environ.get('SENDGRID_API_KEY'))
        # response = sg.send(message)
        sg.send(message)
        return jsonify({'status': True}), 200
    except Exception as e:
        return jsonify({'status':False}), 404
    
@app.post('/api/verify/<token>')
def verify_token(token):
    print("token = ",token)
    try:
        decoded = jwt.decode(token, 'chatsavvy_secret', algorithms="HS256")

        email = decoded['email']
        expired_time = datetime.fromisoformat(decoded['expired_time'])

        print('expired_time:', expired_time)
        print('utc_time:', datetime.utcnow())
        if expired_time < datetime.utcnow():
            return  jsonify({'message': 'Expired time out'}), 404
        
        connection = get_connection()
        cursor = connection.cursor(cursor_factory=extras.RealDictCursor)

        cursor.execute('SELECT * FROM users WHERE email = %s', (email, ))
        user = cursor.fetchone()
        print('user = ', user)
        if user is not None:
            payload = {
                'email': email
            }
            token = jwt.encode(payload, 'chatsavvy_secret', algorithm='HS256')
            return jsonify({'token': 'Bearer: '+token, 'email': email}), 200

        cursor.execute('INSERT INTO users(email) VALUES (%s) RETURNING *',
                    (email))
        new_created_user = cursor.fetchone()
        print(new_created_user)

        connection.commit()
        

        payload = {
            'email': email
        }
        token = jwt.encode(payload, 'chatsavvy_secret', algorithm='HS256')

        cursor.close()
        connection.close()
        return jsonify({'token': 'Bearer: '+token, 'email': email}), 200

    except:
        return jsonify({'message': 'Email already exist'}), 404

@app.post('/api/auth/loginCheck')
def api_loginCheck():
    requestInfo = request.get_json()
    auth_email = requestInfo['email']
    headers = request.headers
    bearer = headers.get('Authorization')
    try:
        token = bearer.split()[1]
        decoded = jwt.decode(token, 'chatsavvy_secret', algorithms="HS256")

        email = decoded['email']

        if(email != auth_email):
            return jsonify({'authentication': False}), 404

        connection = get_connection()
        cursor = connection.cursor(cursor_factory=extras.RealDictCursor)
    
        cursor.execute('SELECT * FROM users WHERE email = %s', (email, ))
        user = cursor.fetchone()

        if user is not None:
            return jsonify({'authentication': True}), 200
        else: return jsonify({'authentication': False}), 404
    except: 
        return jsonify({'authentication': False}), 404

# Serve REACT static files
@app.route('/', methods=['GET'])
def run():
    return 'server is running'

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000,debug=True, threaded=True)