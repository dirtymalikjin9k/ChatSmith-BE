import gevent.monkey
gevent.monkey.patch_all()
import sys
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from werkzeug.utils import secure_filename
import os
import io
import time
import psycopg2
import hashlib
from flask import Flask, flash, render_template, request, redirect, url_for, jsonify, send_from_directory
from flask_cors import CORS
from ask import delete_data_collection, delete_collection
from psycopg2 import connect, extras
from os import environ
import json
import shutil
import stripe
from datetime import datetime, timedelta, date
import jwt
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
import re
import pickle
import boto3
import botocore
import uuid
from dotenv import load_dotenv
from flask_socketio import SocketIO, join_room, leave_room, close_room, rooms
from langchain.embeddings import OpenAIEmbeddings
from langchain.vectorstores import Chroma
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.document_loaders import PyPDFLoader, TextLoader
from langchain.chat_models import ChatOpenAI
from langchain.callbacks import get_openai_callback
from langchain.memory import ConversationTokenBufferMemory
from langchain.chains.question_answering import load_qa_chain
from langchain.prompts import PromptTemplate
from typing import Any, Dict, List
from langchain.callbacks.streaming_stdout import StreamingStdOutCallbackHandler
from langchain.schema import LLMResult
from calendar import monthrange


# below lines should be included on render.com
__import__('pysqlite3')

sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')

app = Flask(__name__, static_folder='build')
app.config['CACHE_TYPE'] = "null"
socketio = SocketIO(app=app, cors_allowed_origins="*"
        , async_mode='gevent')

socketio.init_app(app, cors_allowed_origins="*")

s3 = boto3.client("s3", aws_access_key_id=environ.get(
    'S3_KEY'), aws_secret_access_key=environ.get('S3_SECRET'))

load_dotenv()

if environ.get('OPENAI_API_KEY') is not None:
    os.environ["OPENAI_API_KEY"] = environ.get('OPENAI_API_KEY')

CORS(app, resources={r"/api/*": {"origins": "*"}})

os.makedirs("data", exist_ok=True)

stripe.api_key = environ.get('STRIPE_API_KEY')

endpoint_secret = environ.get('END_POINT_SECRET')

all_urls = set()

host = environ.get('DB_HOST')
port = environ.get('DB_PORT')
dbname = environ.get('DB_NAME')
user = environ.get('DB_USER')
password = environ.get('DB_PASSWORD')


class StreamingHandler(StreamingStdOutCallbackHandler):

    def __init__(self) -> None:
        super().__init__()

    def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any) -> None:
        print('started')
        return super().on_llm_start(serialized=serialized, prompts=prompts)

    def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
        print(token)
        handle_message(token=token)
        return super().on_llm_new_token(token=token, kwargs=kwargs)

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        print('streamign ended')
        return super().on_llm_end(response=response, kwargs=kwargs)


class StreamingCallBack(StreamingStdOutCallbackHandler):
    email = ''

    def __init__(self, email) -> None:
        self.email = email
        super().__init__()

    def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any) -> None:
        return super().on_llm_start(serialized, prompts, **kwargs)

    def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
        handle_message(token=token, email=self.email)
        return super().on_llm_new_token(token, **kwargs)

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        return super().on_llm_end(response, **kwargs)


def get_connection():
    conection = connect(host=host,
                        port=port,
                        dbname=dbname,
                        user=user,
                        password=password)
    return conection


def fetch_sitemap_urls(sitemap_url):
    try:
        response = requests.get(sitemap_url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'lxml')
        excluded_extensions = ['.jpg', '.png', '.gif', '.jpeg', '.svg', '.webp',
                               '.pdf', '.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx',
                               '.mp3', '.mp4', '.avi', '.mov', '.mkv', '.ogg', '.wav']
        excluded_patterns = ['/s/files/']
        all_urls = []
        # If this is a sitemap index
        sitemap_tags = soup.find_all('sitemap')
        if sitemap_tags:
            for sitemap in sitemap_tags:
                loc = sitemap.find('loc').text
                # Recursively fetch URLs from each sitemap
                all_urls.extend(fetch_sitemap_urls(loc))
        else:
            # This is a standard sitemap
            all_urls = [
                element.text for element in soup.find_all('loc')
                if not any(element.text.endswith(ext) for ext in excluded_extensions)
                and not any(pattern in element.text for pattern in excluded_patterns)
            ]
        return all_urls

    except requests.RequestException as e:
        print(f"fetching Error fetching the sitemap: {e}")
        return []


def is_one_month(given_date, today):
    print('give:', given_date)
    print('today:', today)
    x = today.month - 1
    previous_month = 12 if x == 0 else x
    year = today.year - 1 if x == 0 else today.year
    last_day_of_previous_month = monthrange(year, previous_month)[1]
    day = last_day_of_previous_month if today.day > last_day_of_previous_month else today.day
    one_month_ago = date(year, previous_month, day)
    print('one month ago:', one_month_ago)
    if today.month == 2:
        if given_date.month == today.month-1 and given_date.year == today.year and given_date.day >= 28:
            print('not yet')
            return False
    if today.month == 4 or today.month == 6 or today.month == 9 or today.month == 11:
        if given_date.month == today.month-1 and given_date.day == 31:
            print('not yet')
            return False
    if one_month_ago == given_date:
        print('exactly one month ago')
        return True
    else:
        print('one month after or else:', one_month_ago - given_date)
        return False


def next_month(x):
    try:
        nextmonthdate = x.replace(month=x.month+1)
    except ValueError:
        if x.month == 12:
            nextmonthdate = x.replace(year=x.year+1, month=1)
        else:
            # next month is too short to have "same date"
            # pick your own heuristic, or re-raise the exception:
            nextmonthdate = x + 30
    return nextmonthdate


def scrape_urls(urls, root_url, user_email, bot_id):
    user_email_hash = create_hash(user_email)
    data_directory = f"data/{user_email_hash}/{bot_id}"
    # os.makedirs(data_directory, exist_ok=True)
    unique_content = set()
    unique_urls = set()

    dirs = os.path.dirname(f"{data_directory}/url{bot_id}.txt")
    os.makedirs(dirs, exist_ok=True)

    try:
        for url in urls:
            # time.sleep(5)
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'}
            page = requests.get(url, headers=headers)
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
            path = urljoin(root_url, url +
                           '/').replace(root_url, "").strip("/")
            if path == "":
                path = "index"
            else:
                # Replace slashes with hyphens
                path = path.replace("/", "-")
            # Create the directory if it doesn't exist

            # # Write the page content and URLs to a file
            with open(f"{data_directory}/url{bot_id}.txt", "a") as f:
                f.write(f"{title}: {url}\n")
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

        s3.upload_file(f"{data_directory}/url{bot_id}.txt", environ.get('S3_BUCKET'),
                       f"{data_directory}/url{bot_id}.txt", ExtraArgs={'ACL': 'public-read'})

    except Exception as e:
        print('Error on scraping url: ' + str(e))
        return


def check_for_pdf_files(folder_path):
    if not os.path.exists(folder_path):
        return False

    pdf_files = [file for file in os.listdir(
        folder_path) if file.lower().endswith('.pdf')]

    if pdf_files:
        return True
    else:
        return False


user_rooms = {}


@socketio.on('join')
def on_join(data):
    username = data['username']
    room = data['room']
    user_rooms[username] = room
    join_room(room)
    print(username + ' has entered the room ', room)


@socketio.on('connect')
def handle_connect():
    print('connected:')


@socketio.on('disconnect')
def handle_disconnect():
    print('disconnected:')


@socketio.on('stream_new_token')
def handle_message(token, email):
    room = user_rooms[email]
    socketio.emit('stream_new_token', token, room=room)


@app.post('/api/chat')
def api_ask():
    requestInfo = request.get_json()
    auth_email = requestInfo['email']
    bot_id = requestInfo['bot_id']
    headers = request.headers
    bearer = headers.get('Authorization')
    query = request.json['message_text']
    try:
        token = bearer.split()[1]
        decoded = jwt.decode(token, 'chatsavvy_secret', algorithms="HS256")
        email = decoded['email']

        if (email != auth_email):
            return jsonify({'message': 'Authrization is faild'}), 404
            
        connection = get_connection()
        cursor = connection.cursor(cursor_factory=extras.RealDictCursor)
        cursor.execute(
            'SELECT * FROM subscription where email = %s order by id desc', (email,))
        subscription = cursor.fetchone()
        ts = datetime.now().timestamp()
        if subscription is None:
            cursor.execute('INSERT INTO subscription(email, customer_id, subscription_id, start_date, end_date, type, message_left) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *',
                           (email, '', '', ts, ts, 'free', 49))
            connection.commit()

        else:
            leftCount = int(subscription['message_left']) - 1
            if leftCount < 0:
                return jsonify({'type': 'low_connect'}), 500
            cursor.execute(
                'update subscription set message_left = %s where id = %s', (leftCount, subscription['id'],))
            connection.commit()

        user_email_hash = create_hash(email)
        data_directory = f"data/{user_email_hash}/{bot_id}"
        os.makedirs(name=data_directory, exist_ok=True)

        response = s3.list_objects_v2(Bucket=environ.get(
            'S3_BUCKET'), Prefix=data_directory)

        documents = []
        for obj in response.get('Contents', []):
            file_key = obj['Key']
            try:
                newFileName = f"data/{uuid.uuid4()}"
                s3.download_file(environ.get('S3_BUCKET'), file_key, newFileName)

                if file_key.lower().endswith(".pdf"):
                    loader = PyPDFLoader(newFileName)
                elif file_key.lower().endswith(".txt"):
                    loader = TextLoader(newFileName)
                # Use TextLoader to process text content
                documents += loader.load()
                os.remove(newFileName)
            except:
                continue

        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=2000, chunk_overlap=50)

        texts = text_splitter.split_documents(documents)
        docsearch = Chroma(user_email_hash).from_documents(texts, OpenAIEmbeddings())
        connection = get_connection()
        cursor = connection.cursor(cursor_factory=extras.RealDictCursor)
        cursor.execute(
            'SELECT * FROM chats WHERE email = %s AND bot_id = %s', (email, bot_id))
        chat = cursor.fetchone()
        bot_prompt = chat['bot_prompt']
        bot_name = chat['bot_name']
        uniqueId = chat['bot_name']

        template = bot_prompt + """
        {context}

        {chat_history}

        Human: {human_input}
        Chatbot: """

        prompt = PromptTemplate(
            input_variables=["chat_history", "human_input", "context"],
            template=template
        )

        llm = ChatOpenAI(model="gpt-3.5-turbo",
                         streaming=True,
                         callbacks=[StreamingCallBack(email)],
                         temperature=0.0)

        memory = ConversationTokenBufferMemory(
            llm=llm, max_token_limit=5000, memory_key="chat_history", input_key="human_input")
        cursor.execute(
            'SELECT * FROM botchain WHERE botid = %s AND email = %s', (bot_id, email,))
        chain = cursor.fetchone()
        connection.commit()
        if chain is None:
            conversation_chain = load_qa_chain(
                llm=llm, chain_type="stuff", memory=memory, prompt=prompt)
        else:
            chain_memory = chain['chain']
            exist_conversation_chain = pickle.loads(bytes(chain_memory))
            conversation_chain = load_qa_chain(
                llm=llm, chain_type="stuff", memory=exist_conversation_chain.memory, prompt=prompt)

        with get_openai_callback() as cb:
            docs = docsearch.similarity_search(query)
            conversation_chain(
                {"input_documents": docs, "human_input": query, "chat_history": ""}, return_only_outputs=True)
            text = conversation_chain.memory.buffer[-1].content
        memory.load_memory_variables({})
        new_chain = pickle.dumps(conversation_chain)
        if chain is None:
            cursor.execute('INSERT INTO botchain(email, botid, chain) VALUES (%s, %s, %s) RETURNING *',
                           (email, bot_id, new_chain))
        else:
            cursor.execute(
                'UPDATE botchain SET chain = %s WHERE email = %s AND botid = %s', (new_chain, email, bot_id, ))
        connection.commit()
        # Check if the response contains a link
        url_pattern = re.compile(r"(?P<url>https?://[^\s]+)")

        # replace URLs with anchor tags in the text
        response = url_pattern.sub(
            r"<a href='\g<url>' target='_blank' style='color: #0000FF'>\g<url></a>", text)
        response = response.replace("[", "").replace("]", "")
        response = response.replace("(", "").replace(")", "")
        response = response.rstrip(".")
        newMessage = {
            "question": query,
            "answer": response
        }

        cur = connection.cursor(cursor_factory=extras.RealDictCursor)
        cur.execute(
            'SELECT * FROM chats WHERE email = %s AND bot_id = %s', (email, bot_id))
        chat = cur.fetchone()
        chat_content = chat['chats']
        chat_content.append(newMessage)
        updated_json_data_string = json.dumps(chat_content)
        cur.execute("UPDATE chats SET chats = %s WHERE email = %s AND bot_id = %s",
                    (updated_json_data_string, email, bot_id))

        # Insert into embedhistory to show in history tab
        cur.execute('select chat_id from bot_id_history where bot_name = %s', (bot_name,))
        chatId = cur.fetchone()
        chatNumber = '0'
        if chatId is not None:
            chatNumber = f"{int(chatId['chat_id']) + 1}"

        cur.execute('SELECT * FROM embedhistory WHERE email = %s AND name = %s AND url = %s and chat_id = %s',
                    (email, bot_name, uniqueId, chatNumber,))
        chat = cur.fetchone()
        now = datetime.now()
        datestr = f"{now}"
        if chat is None:  # create new history
            chatStr = json.dumps([newMessage])
            cursor.execute('INSERT INTO embedhistory(email, name, url, chats, create_time, chat_id) VALUES (%s, %s, %s, %s, %s, %s)',
                           (email, bot_name, uniqueId, chatStr, datestr, chatNumber,))
        else:
            chat_content = chat['chats']
            chat_content.append(newMessage)
            chatStr = json.dumps(chat_content)
            cursor.execute('UPDATE embedhistory set chats = %s, create_time = %s where name = %s and url = %s and chat_id = %s',
                           (chatStr, datestr, bot_name, uniqueId, chatNumber))
        connection.commit()
        cur.close()
        connection.close()

        return jsonify({'message': response}), 200
    except Exception as e:
        print('Error: ' + str(e))
        return jsonify({'message': 'Bad Request'}), 404


@app.post('/api/chatsDelete')
def api_chats_delte():
    requestInfo = request.get_json()
    auth_email = requestInfo['email']
    bot_id = requestInfo['bot_id']
    headers = request.headers
    bearer = headers.get('Authorization')
    try:
        token = bearer.split()[1]
        decoded = jwt.decode(token, 'chatsavvy_secret', algorithms="HS256")

        email = decoded['email']

        if (email != auth_email):
            return jsonify({'message': 'Authrization is faild'}), 404
        # new_client = chromadb.PersistentClient()
        # new_client.get_or_create_collection(
        #     str(create_hash(email)+str(bot_id)))
        # new_client.delete_collection(str(create_hash(email)+str(bot_id)))

        response = delete_data_collection(auth_email, bot_id)
        connection = get_connection()
        cursor = connection.cursor(cursor_factory=extras.RealDictCursor)
        cursor.execute('DELETE FROM botchain WHERE email = %s AND botid = %s',
                       (email, bot_id))
        connection.commit()

        cursor.execute('select bot_name from chats where email = %s and bot_id = %s', (email, bot_id))
        bot = cursor.fetchone()
        botname = bot['bot_name']
        cursor.execute('select chat_id from bot_id_history where bot_name = %s', (botname,))
        chatId = cursor.fetchone()

        if chatId is None:
            cursor.execute('insert into bot_id_history(bot_name, chat_id) values (%s, %s)', (botname, '0',))
            connection.commit()
        else:
            cursor.execute('update bot_id_history set chat_id = %s where bot_name = %s', (f"{int(chatId['chat_id']) + 1}", botname))
            connection.commit()

        cursor.close()
        connection.close()
        if response:
            return jsonify({'message': 'Delete Success'}), 200
        else:
            return jsonify({'message': 'bad request'}), 404
    except Exception as e:
        print('bot delet error:', str(e))
        return jsonify({'message': 'bad request'}), 404


@app.post('/api/botDelete')
def api_bot_delete():
    requestInfo = request.get_json()
    auth_email = requestInfo['email']
    bot_id = requestInfo['bot_id']
    headers = request.headers
    bearer = headers.get('Authorization')
    try:
        token = bearer.split()[1]
        decoded = jwt.decode(token, 'chatsavvy_secret', algorithms="HS256")

        email = decoded['email']

        if (email != auth_email):
            return jsonify({'message': 'Authrization is faild'}), 404
        # new_client = chromadb.PersistentClient()
        # new_client.get_or_create_collection(
        #     str(create_hash(email)+str(bot_id)))
        # new_client.delete_collection(str(create_hash(email)+str(bot_id)))

        connection = get_connection()
        cursor = connection.cursor(cursor_factory=extras.RealDictCursor)
        cursor.execute('DELETE FROM chats WHERE email = %s AND bot_id = %s',
                       (email, bot_id))
        connection.commit()

        cursor.execute('DELETE FROM botchain WHERE email = %s AND botid = %s',
                       (email, bot_id))
        connection.commit()

        cursor.close()
        connection.close()
        user_email_hash = create_hash(email)
        data_directory = f"data/{user_email_hash}/{bot_id}"
        objects = s3.list_objects_v2(Bucket=environ.get(
            'S3_BUCKET'), Prefix=data_directory)
        for object in objects['Contents']:
            s3.delete_object(Bucket=environ.get(
                'S3_BUCKET'), Key=object['Key'])
        shutil.rmtree(data_directory)
        return jsonify({'message': 'Chatbot Deleted'}), 200
    except Exception as e:
        print('bot delete Error: ' + str(e))
        return jsonify({'message': 'bad request'}), 404


def verify_google_token(token):
    # Specify the client ID of the Google API Console project that the credential is from
    CLIENT_ID = '241041186069-4k2k1pt0b20t1fs8q77nmnl3po9cr6ub.apps.googleusercontent.com'

    try:
        # Verify and decode the token
        # decoded_token = id_token.verify_oauth2_token(token, google_requests.Request(), CLIENT_ID)
        url = 'https://www.googleapis.com/oauth2/v3/userinfo'
        headers = {'Authorization': f'Bearer {token}'}

        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            user_info = response.json()
            return user_info
        else:
            print(f"verify google token error: {response.status_code}")
            return None

        # Assuming you have the access token in a variable called 'access_token'

    except Exception as e:
        print("verify google token 2 error:", str(e))
        # Handle invalid token error
        return None


@app.post('/api/auth/googleLogin')
def api_auth_googleLogin():
    requestInfo = request.get_json()
    email = requestInfo['email']
    credential = requestInfo['credential']
    print('cred:', requestInfo)
    try:
        responsePayload = verify_google_token(credential)
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

        cursor.execute('select id from users order by id DESC limit 1')
        id = cursor.fetchone()
        newId = id['id'] + 1 if id is not None else 1
        cursor.execute('INSERT INTO users(id, email) VALUES (%s, %s) RETURNING *',
                       (newId, email,))

        connection.commit()
        cursor.close()
        connection.close()

        payload = {
            'email': email
        }
        token = jwt.encode(payload, 'chatsavvy_secret', algorithm='HS256')

        return jsonify({'token': 'Bearer: '+token, 'email': email}), 200

    except Exception as e:
        print('step error', str(e))
        return jsonify({'message': 'Bad request'}), 404


@app.post('/api/fetchPage')
def api_fetchPage():
    try:
        requestInfo = request.get_json()
        url = requestInfo['url']

        urls = sorted(fetch_sitemap_urls(f"{url}/sitemap.xml"))

        return jsonify({'urls': urls}), 200
    except Exception as e:
        print('fetching page error:' + str(e))
        return jsonify({'message': 'Fetching Error'}), 402


@app.post('/api/newChat')
def api_newChat():

    try:
        requestInfo = dict(request.form)
        auth_email = requestInfo.get('email')
        instance_name = requestInfo.get('instace_name')
        bot_name = f"{uuid.uuid1()}"
        bot_avatar = request.files.get('bot_avatar')
        bot_id = requestInfo.get('bot_id')
        urls_input = requestInfo.get('urls_input')
        bot_prompt = requestInfo.get('bot_prompt')

        filename = ''
        if bot_avatar:
            bot_avatar = bot_avatar.read()

        files = request.files.getlist('files')
        user_email_hash = create_hash(auth_email)
        data_directory = f"data/{user_email_hash}/{bot_id}"
        # os.makedirs(data_directory, exist_ok=True)
        if len(files) > 0:
            upload_files_size = 0

            for file in files:
                # file.save(data_directory + "/" + file.filename)
                upload_files_size += file.seek(0, 2)

                file.seek(0)
                s3.upload_fileobj(
                    file,
                    environ.get('S3_BUCKET'),
                    f"{data_directory}/{file.filename}",
                    ExtraArgs={
                        "ACL": "public-read",
                        "ContentType": file.content_type
                    }
                )

            data_path = f"data/{user_email_hash}"
            if upload_files_size + folder_size(data_path) > 10 * 1024 * 1024:
                for file in files:
                    s3.delete_object(Bucket=environ.get('S3_BUCKET'),
                                     Key=f"{data_directory}/{file.filename}")
                return jsonify({'message': 'You can upload the files total 10MB'}), 404

        chats = [{
            "question": "",
            "answer": ""
        }]

        default_bot_prompt = "Answer the following question using only the information provided and give a link at the end of your response to a page where they can find more information for what they're looking for. Do not answer questions unrelated to the context provided. NEVER make anything up or provide false information that is not found in the provided context. If you are unsure, simply let the user know."

        headers = request.headers
        bearer = headers.get('Authorization')

        token = bearer.split()[1]
        decoded = jwt.decode(token, 'chatsavvy_secret', algorithms="HS256")

        email = decoded['email']

        if (email != auth_email):
            return jsonify({'message': 'Authrization is faild'}), 404

        if bot_prompt == "":
            bot_prompt = default_bot_prompt

        connection = get_connection()
        cursor = connection.cursor(cursor_factory=extras.RealDictCursor)
        chats_str = json.dumps(chats)
        now = f"{datetime.now()}"
        cursor.execute('INSERT INTO chats (email, instance_name, bot_name, bot_avatar, pdf_file, urls, bot_prompt, bot_id, chats, complete, created) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *',
                       (email, instance_name, bot_name, psycopg2.Binary(bot_avatar), filename, urls_input, bot_prompt, bot_id, chats_str, 'false', now))
        connection.commit()

        cursor.execute('SELECT * FROM subscription where email = %s', (email,))
        subscription = cursor.fetchone()
        connection.commit()

        urls = [url.strip() for url in urls_input.split(",")]

        if (subscription is None):
            urls = urls[:2]
        else:
            end_time = datetime.fromtimestamp(float(subscription['end_date']))
            current_time = datetime.now()

            if (current_time > end_time):
                urls = urls[:2]

        root_url = urljoin(urls[0], "/")
        scrape_urls(urls, root_url, email, bot_id)

        initial_welcome = {
            'enable': True,
            'welcome': 'Welcome to our site! Ask me anything about our website!'
        }

        cursor.execute(
            'UPDATE chats SET complete = %s, welcome_message = %s WHERE email = %s AND bot_id = %s', ('true', json.dumps(initial_welcome), email, bot_id))
        # new_created_chat = cursor.fetchone()

        connection.commit()
        cursor.close()
        connection.close()

        return jsonify({'message': 'Success Create'}), 200
    except Exception as e:
        print('create chat bot Error: ' + str(e))
        return jsonify({'message': 'Bad Request'}), 404


ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif'}


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def delete_text_files(directory):
    objects = s3.list_objects_v2(
        Bucket=environ.get('S3_BUCKET'), Prefix=directory)

    if hasattr(objects, 'Contents'):
        for object in objects['Contents']:
            if object['Key'].lower().endswith(".txt"):
                s3.delete_object(Bucket=environ.get(
                    'S3_BUCKET'), Key=object['Key'])


@app.post('/api/updateChat')
def api_updateChat():
    auth_email = request.form.get('email')
    instance_name = request.form.get('instance_name')
    bot_id = request.form.get('bot_id')
    urls_input = request.form.get('urls_input')
    bot_prompt = request.form.get('prompt')
    welcome = request.form.get('welcome')
    label = request.form.get('label')
    bot_color = request.form.get('bot_color')
    custom_text = request.form.get('custom_text')
    remove_files = request.form.getlist('remove_files')
    headers = request.headers
    bearer = headers.get('Authorization')
    files = request.files.getlist('files')
    bot_avatar = request.files.get('bot_avatar')

    if bot_avatar:
        bot_avatar = bot_avatar.read()
    user_email_hash = create_hash(auth_email)

    try:
        token = bearer.split()[1]
        decoded = jwt.decode(token, 'chatsavvy_secret', algorithms="HS256")

        email = decoded['email']

        if (email != auth_email):
            return jsonify({'message': 'Authrization is faild'}), 404
        # new_client = chromadb.PersistentClient()
        # new_client.get_or_create_collection(
        #     str(create_hash(email)+str(bot_id)))
        # new_client.delete_collection(str(create_hash(email)+str(bot_id)))
        user_email_hash = create_hash(email)
        data_directory = f"data/{user_email_hash}/{bot_id}"
        try:
            shutil.rmtree(data_directory)
        except Exception as e:
            print('delete error:', e)

        # delete all related datas and history.
        delete_data_collection(email, bot_id)
        connection = get_connection()
        cursor = connection.cursor(cursor_factory=extras.RealDictCursor)

        cursor.execute('select bot_name from chats where email = %s and bot_id = %s', (email, bot_id))
        bot = cursor.fetchone()
        botname = bot['bot_name']
        cursor.execute('select chat_id from bot_id_history where bot_name = %s', (botname,))
        chatId = cursor.fetchone()

        if chatId is None:
            cursor.execute('insert into bot_id_history(bot_name, chat_id) values (%s, %s)', (botname, '0',))
            connection.commit()
        else:
            cursor.execute('update bot_id_history set chat_id = %s where bot_name = %s', (f"{int(chatId['chat_id']) + 1}", botname))
            connection.commit()

        cursor.execute('UPDATE chats SET complete = %s WHERE email = %s AND bot_id = %s', ('false', email, bot_id))
        connection.commit()

        if len(files) > 0 or len(remove_files) > 0:  # pdf update
            if len(remove_files) > 0:
                for remove_file in remove_files:
                    delete_pdf_files(data_directory, remove_file)
                cursor.execute('UPDATE chats SET complete = %s WHERE email = %s AND bot_id = %s', ('true', email, bot_id))
                connection.commit()
                
            if len(files) > 0:
                upload_files_size = 0

                for file in files:
                    upload_files_size += file.seek(0, 2)

                    file.seek(0)
                    s3.upload_fileobj(
                        file,
                        environ.get('S3_BUCKET'),
                        f"{data_directory}/{file.filename}",
                        ExtraArgs={
                            "ACL": "public-read",
                            "ContentType": file.content_type
                        }
                    )

                cursor.execute('UPDATE chats SET complete = %s WHERE email = %s AND bot_id = %s', ('true', email, bot_id))
                connection.commit()
                data_path = f"data/{user_email_hash}"
                if upload_files_size + folder_size(data_path) > 10 * 1024 * 1024:
                    for file in files:
                        s3.delete_object(Bucket=environ.get(
                            'S3_BUCKET'), Key=f"{data_directory}/{file.filename}")
                    return jsonify({'message': 'You can upload the files total 10MB'}), 403

            return jsonify({'message': 'Update Success'}), 200

        elif urls_input is not None:  # url update
            delete_text_files(data_directory)
            urls = [url.strip() for url in urls_input.split(",")]
            root_url = urljoin(urls[0], "/")
            scrape_urls(urls, root_url, email, bot_id)

            cursor.execute(
                "update chats set urls = %s, complete = %s where email = %s and bot_id = %s", (urls_input, 'true', email, bot_id))
            connection.commit()
            cursor.close()
            connection.close()
            return jsonify({'message': 'Update Success'}), 200

        else:  # normal update
            # if custom_text != "":

            #     # filename = f"{data_directory}/custom_text.txt"
            #     filename = os.path.join(data_directory, 'custom_text.txt')
            #     with open(filename, "x") as file:
            #         file.write(custom_text)

            s3.delete_object(Bucket=environ.get(
                'S3_BUCKET'), Key=f"{data_directory}/custom_text.txt")
            # s3.upload_file(f"{data_directory}/custom_text.txt",
            #                environ.get('S3_BUCKET'), f"{data_directory}/custom_text.txt", ExtraArgs={'ACL': 'public-read'})
            s3.put_object(Body=custom_text, Bucket=environ.get(
                'S3_BUCKET'), Key=f"{data_directory}/custom_text.txt", ACL='public-read')

            cursor.execute("UPDATE chats SET instance_name = %s, pdf_file = %s, bot_prompt = %s, custom_text = %s, complete = %s WHERE email = %s AND bot_id = %s",
                           (instance_name, bot_color, bot_prompt, custom_text, 'false', email, bot_id))
            connection.commit()

            if bot_avatar:
                cursor.execute("UPDATE chats SET bot_avatar = %s WHERE email = %s AND bot_id = %s",
                               (psycopg2.Binary(bot_avatar), email, bot_id))
                connection.commit()

            cursor.execute('DELETE FROM botchain WHERE email = %s AND botid = %s',
                           (email, bot_id))
            connection.commit()

            cursor.execute("UPDATE chats SET instance_name = %s, bot_prompt = %s, custom_text = %s, complete = %s, welcome_message = %s, label = %s WHERE email = %s AND bot_id = %s",
                           (instance_name, bot_prompt, custom_text, 'true', welcome, label, email, bot_id))
            connection.commit()
            cursor.close()
            connection.close()
            return jsonify({'message': 'Update Success'}), 200

    except Exception as e:
        print('update chat bot Error: ' + str(e))
        # return jsonify({'message': 'Bad Request'}), 404


@app.post('/api/getChatInfos')
def api_getChatInfos():
    requestInfo = request.get_json()
    auth_email = requestInfo['email']
    headers = request.headers
    bearer = headers.get('Authorization')
    try:
        token = bearer.split()[1]
        decoded = jwt.decode(token, 'chatsavvy_secret', algorithms="HS256")

        email = decoded['email']

        if (email != auth_email):
            return jsonify({'message': 'Authrization is faild'}), 404
        connection = get_connection()
        cursor = connection.cursor(cursor_factory=extras.RealDictCursor)

        try:
            cursor.execute(
                "SELECT id, email, welcome_message, label, instance_name, custom_text, bot_id, chats, complete, created, urls, bot_name, bot_prompt, pdf_file, encode(bot_avatar, 'base64') AS avatar FROM chats WHERE email = %s ", (email,))  # bot_avatar, pdf_file is missing.
            chats = cursor.fetchall()
            connection.commit()
            cursor.close()
            connection.close()

            return jsonify({'chats': chats})
        except Exception as e:
            print(' get chat bot 1 Error: ' + str(e))
            return jsonify({'message': 'chat does not exist'}), 404
    except Exception as e:
        print('get chat bot 2 Error: ' + str(e))
        return jsonify({'message': 'bad request'}), 404


@app.post('/api/webhook')
def api_webhook():
    event = None
    payload = request.data
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
    charge = session = invoice = updated = deleted = None
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        print("session = ", session)
    elif event['type'] == 'charge.succeeded':
        charge = event['data']['object']
        print("charge = ", charge)
    elif event['type'] == 'invoice.paid':
        invoice = event['data']['object']
        print("invoice = ", invoice)
    # ... handle other event types
    elif event['type'] == 'customer.subscription.updated':
    # elif event['type'] == 'invoice.updated':
        updated = event['data']['object']
        print('updated:', updated)
    elif event['type'] == 'customer.subscription.deleted':
        deleted = event['data']['object']
        print('deleted:', deleted)
    else:
        print('Unhandled event type {}'.format(event['type']))

    print("Webhook event recognized:", event['type'])

    connection = get_connection()
    cursor = connection.cursor(cursor_factory=extras.RealDictCursor)
    if invoice:

        email = invoice['customer_email']
        print("email = ", email)
        customer_id = invoice['customer']
        subscription_id = invoice['subscription']
        print("customer_id = ", customer_id)
        start_date = invoice['lines']['data'][0]['period']['start']
        end_date = invoice['lines']['data'][0]['period']['end']
        amount = invoice['lines']['data'][0]['amount_excluding_tax']

        payType = 'free'
        period = 'monthly'
        if amount == 100:
            payType = 'standard'
            period = 'monthly'
        elif amount == 1:
            payType = 'hobby'
            period = 'monthly'
        elif amount == 1900:
            payType = 'hobby'
            period = 'monthly'
        elif amount == 4900:
            payType = 'standard'
            period = 'monthly'
        elif amount == 9900:
            payType = 'pro'
            period = 'monthly'
        elif amount == 19000:
            payType = 'hobby'
            period = 'annually'
        elif amount == 49000:
            payType = 'standard'
            period = 'annually'
        elif amount == 99000:
            payType = 'pro'
            period = 'annually'

        cursor.execute('select subscription_id from subscription where customer_id = %s', (customer_id,))
        subscription = cursor.fetchone()
        if subscription is not None and subscription_id != subscription['subscription_id']:
            try:
                stripe.Subscription.cancel(subscription['subscription_id'])
            except:
                a = 2

        cursor.execute('select * from plans where type = %s', (payType,))
        detail = cursor.fetchone()
        if payType == 'trial':
            messageCount = 20
        else:
            messageCount = detail['detail']['monthMessage']

        cursor.execute('update subscription set customer_id = %s, subscription_id = %s, start_date = %s, end_date = %s, type = %s, message_left = %s, period = %s where email = %s',
                       (customer_id, subscription_id, start_date, end_date, payType, messageCount, period, email))

    if updated:
        customer_id = updated['customer']
        subscription_id = updated['items']['data'][0]['subscription']
        amount = updated['plan']['amount']
        start_date = updated['current_period_start']
        end_date = updated['current_period_end']
        payType = 'free'
        period = 'monthly'
        if amount == 100:
            payType = 'standard'
            period = 'monthly'
        elif amount == 1900:
            payType = 'hobby'
            period = 'monthly'
        elif amount == 1:
            payType = 'hobby'
            period = 'monthly'
        elif amount == 4900:
            payType = 'standard'
            period = 'monthly'
        elif amount == 9900:
            payType = 'pro'
            period = 'monthly'
        elif amount == 19000:
            payType = 'hobby'
            period = 'annually'
        elif amount == 49000:
            payType = 'standard'
            period = 'annually'
        elif amount == 99000:
            payType = 'pro'
            period = 'annually'

        cursor.execute('select * from plans where type = %s', (payType,))
        detail = cursor.fetchone()
        if payType == 'trial':
            messageCount = 20
        else:
            messageCount = detail['detail']['monthMessage']

        cursor.execute('update subscription set subscription_id = %s, start_date = %s, end_date = %s, type = %s, message_left = %s, period = %s where customer_id = %s',
                       (subscription_id, start_date, end_date, payType, messageCount, period, customer_id))

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

        if (email != auth_email):
            return jsonify({'message': 'Authrization is faild'}), 404

        connection = get_connection()
        cursor = connection.cursor(cursor_factory=extras.RealDictCursor)
        # try:
        cursor.execute(
            'SELECT * FROM subscription WHERE email = %s order by id desc', (email,))

        select = cursor.fetchone()
        connection.commit()
        cursor.execute('select * from plans where type = %s', ('free',))
        plan = cursor.fetchone()

        if select is None:
            ts = int(datetime.now().timestamp())
            cursor.execute('INSERT INTO subscription(email, customer_id, subscription_id, start_date, end_date, type, message_left) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *',
                           (email, '', '', ts, ts, 'free', 50))
            connection.commit()
            return jsonify({'customerId': '', 'subscriptionId': '', 'type': 'free', 'period': 'month', 'detail': plan['detail'], 'messageLeft': 50})
        else:
            subscription = select
            end_time = datetime.fromtimestamp(float(subscription['end_date']))
            current_time = datetime.now()

            if end_time.date() == current_time.date():
                cursor.execute(
                    'update subscription set message_left = %s, end_date = %s where id = %s', (int(plan['detail']['monthMessage']), next_month(current_time).timestamp(), subscription['id'],))
                connection.commit()

            if end_time > current_time:
                planType = subscription['type']
                cursor.execute(
                    'select * from plans where type = %s', (planType,))
                plan = cursor.fetchone()
                connection.commit()
                # if subscription['message_left'] is None or int(subscription['message_left']) == 0:
                    # cursor.execute(
                    #     'update subscription set message_left = %s where id = %s', (int(plan['detail']['monthMessage']), subscription['id'],))
                    # connection.commit()
                    # return jsonify({'customerId': subscription['customer_id'], 'subscriptionId': subscription['subscription_id'], 'type': planType, 'period': subscription['period'], 'detail': plan['detail'], 'messageLeft': plan['detail']['monthMessage']})
                # else:
                return jsonify({'customerId': subscription['customer_id'], 'subscriptionId': subscription['subscription_id'], 'type': planType, 'period': subscription['period'], 'detail': plan['detail'], 'messageLeft': subscription['message_left']})
            else:
                cursor.execute('select FROM subscription WHERE email = %s order by id desc',
                               (email, ))
                sub = cursor.fetchone()
                print('sub:', sub)
                connection.commit()

                cursor.close()
                connection.close()
                # user_email_hash = create_hash(email)
                # data_directory = f"data/{user_email_hash}"
                # shutil.rmtree(data_directory)
                return jsonify({'customerId': subscription['customer_id'], 'subscriptionId': subscription['subscription_id'], 'type': 'free', 'period': subscription['period'], 'detail': plan['detail'], 'messageLeft': sub['message_left']})
    except Exception as e:
        print('get subscription Error: ' + str(e))
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
    message = Mail(
        from_email='admin@chatsmith.ai',
        to_emails=email,
        subject='Sign in to ChatSmith',
        html_content=f'<p style="color: #500050;">Hello<br/><br/>We received a request to sign in to ChatSmith using this email address {email}. If you want to sign in to your ChatSmith account, click this link:<br/><br/><a href="https://app.chatsmith.ai/#/verify/{token}">Sign in to ChatSmith</a><br/><br/>If you did not request this link, you can safely ignore this email.<br/><br/>Thanks.<br/><br/>Your ChatSmith team.</p>'
    )
    try:
        sg = SendGridAPIClient(api_key=environ.get('SENDGRID_API_KEY'))
        # response = sg.send(message)
        sg.send(message)
        return jsonify({'status': True}), 200
    except Exception as e:
        print("send verify email Error:", str(e))
        return jsonify({'status': False}), 404


@app.post('/api/verify/<token>')
def verify_token(token):
    try:
        decoded = jwt.decode(token, 'chatsavvy_secret', algorithms="HS256")

        email = decoded['email']
        expired_time = datetime.fromisoformat(decoded['expired_time'])

        if expired_time < datetime.utcnow():
            print('here called')
            return jsonify({'message': 'Expired time out'}), 404

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

        connection.commit()

        payload = {
            'email': email
        }
        token = jwt.encode(payload, 'chatsavvy_secret', algorithm='HS256')

        cursor.close()
        connection.close()
        return jsonify({'token': 'Bearer: '+token, 'email': email}), 200

    except Exception as e:
        print('here called.', str(e))
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

        if (email != auth_email):
            return jsonify({'authentication': False}), 404

        connection = get_connection()
        cursor = connection.cursor(cursor_factory=extras.RealDictCursor)

        cursor.execute('SELECT * FROM users WHERE email = %s', (email, ))
        user = cursor.fetchone()

        if user is not None:
            return jsonify({'authentication': True}), 200
        else:
            return jsonify({'authentication': False}), 404
    except:
        return jsonify({'authentication': False}), 404


@app.post('/api/cancelSubscription')
def cancelSubscription():
    requestInfo = request.get_json()
    auth_email = requestInfo['email']
    customer_id = requestInfo['customer_id']
    subscription_id = requestInfo['subscription_id']
    headers = request.headers
    bearer = headers.get('Authorization')
    try:
        token = bearer.split()[1]
        decoded = jwt.decode(token, 'chatsavvy_secret', algorithms="HS256")

        email = decoded['email']

        if (email != auth_email):
            return jsonify({'authentication': False}), 404

        connection = get_connection()
        cursor = connection.cursor(cursor_factory=extras.RealDictCursor)

        cursor.execute('DELETE FROM subscription WHERE email = %s AND customer_id = %s AND subscription_id = %s',
                       (email, customer_id, subscription_id))
        connection.commit()

        cursor.execute('DELETE FROM chats WHERE email = %s', (email, ))
        connection.commit()

        cursor.close()
        connection.close()
        # user_email_hash = create_hash(email)
        # data_directory = f"data/{user_email_hash}"
        # shutil.rmtree(data_directory)
        return jsonify({'message': 'Success deleted'}), 200
    except Exception as e:
        print("cancel subscription error:", str(e))
        return jsonify({'message': 'Bad request'}), 404


@app.post('/api/createEmbedScriptToken')
def makeEmbedScriptToken():
    requestInfo = request.get_json()
    auth_email = requestInfo['email']
    bot_name = requestInfo['bot_name']

    headers = request.headers
    bearer = headers.get('Authorization')
    try:
        token = bearer.split()[1]
        decoded = jwt.decode(token, 'chatsavvy_secret', algorithms="HS256")

        email = decoded['email']

        if (email != auth_email):
            return jsonify({'message': 'Authentication False'}), 403

        connection = get_connection()
        cursor = connection.cursor(cursor_factory=extras.RealDictCursor)

        cursor.execute(
            'SELECT * FROM subscription WHERE email = %s ', (email, ))
        subscription = cursor.fetchone()
        connection.commit()

        if subscription is None:
            return jsonify({'message': 'Subscription does not exist'}), 422

        end_time = datetime.fromtimestamp(int(subscription['end_date']))
        current_time = datetime.now()
        if end_time < current_time:
            return jsonify({'message': 'Expired period'}), 422

        payload = {
            'email': email,
            'bot_name': bot_name,
            'customer_id': subscription['customer_id'],
            'subscription_id': subscription['subscription_id'],
        }
        token = jwt.encode(payload, 'chatsavvy_secret', algorithm='HS256')

        cursor.close()
        connection.close()
        return jsonify({'message': 'Success created', 'token': token}), 200
    except Exception as e:
        print("error:", str(e))
        return jsonify({'message': 'Bad request'}), 404


@app.post('/api/getEmbedChatBotInfo')
def getEmbedChatBotInfo():
    requestInfo = request.get_json()
    token = requestInfo['token']
    try:
        decoded = jwt.decode(token, 'chatsavvy_secret', algorithms="HS256")
        email = decoded['email']
        subscription_id = decoded['subscription_id']
        customer_id = decoded['customer_id']
        bot_name = decoded['bot_name']

        connection = get_connection()
        cursor = connection.cursor(cursor_factory=extras.RealDictCursor)

        cursor.execute(
            'SELECT * FROM subscription WHERE email = %s AND subscription_id = %s AND customer_id = %s', (email, subscription_id, customer_id))
        subscription = cursor.fetchone()
        connection.commit()

        if subscription is None:
            return jsonify({'message': 'Subscription does not exist'}), 404

        cursor.execute(
            "SELECT instance_name, bot_id, label, encode(bot_avatar, 'base64') AS avatar, pdf_file FROM chats WHERE email = %s AND bot_name = %s", (email, bot_name))
        chat = cursor.fetchone()

        if chat is None:
            return jsonify({'message': 'Chat does not exist'}), 404

        return jsonify({'botName': chat['instance_name'], 'botId': chat['bot_id'], 'avatar': chat['avatar'], 'color': chat['pdf_file'], 'label': chat['label'], 'plan': subscription['type']}), 200

    except Exception as e:
        print("get embed chat bot info error:", str(e))
        return jsonify({'message': 'Bad request'}), 404


@app.post('/api/embedChat')
def embedChat():
    print('embed caht called')
    requestInfo = request.get_json()
    token = requestInfo['token']
    query = requestInfo['query']
    uniqueId = requestInfo['unique_id']
    try:
        decoded = jwt.decode(token, 'chatsavvy_secret', algorithms="HS256")
        email = decoded['email']
        subscription_id = decoded['subscription_id']
        customer_id = decoded['customer_id']
        bot_name = decoded['bot_name']

        connection = get_connection()
        cursor = connection.cursor(cursor_factory=extras.RealDictCursor)
        cursor.execute(
            'SELECT * FROM subscription where email = %s order by id desc', (email,))
        subscription = cursor.fetchone()
        ts = datetime.now().timestamp()
        if subscription is None:
            cursor.execute('INSERT INTO subscription(email, customer_id, subscription_id, start_date, end_date, type, message_left) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *',
                           (email, '', '', ts, ts, 'free', 49))
            connection.commit()

        else:
            leftCount = int(subscription['message_left']) - 1
            if leftCount < 0:
                return jsonify({'type': 'low_connect'}), 500
            cursor.execute(
                'update subscription set message_left = %s where id = %s', (leftCount, subscription['id'],))
            connection.commit()


        cursor.execute(
            'SELECT * FROM subscription WHERE email = %s AND subscription_id = %s AND customer_id = %s', (email, subscription_id, customer_id))
        subscription = cursor.fetchone()
        connection.commit()

        if subscription is None:
            return jsonify({'message': 'Subscription does not exist'}), 404

        cur = connection.cursor(cursor_factory=extras.RealDictCursor)
        cur.execute(
            'SELECT * FROM chats WHERE email = %s AND bot_name = %s', (email, bot_name))
        chat = cur.fetchone()

        if chat is None:
            return jsonify({'message': 'Chat does not exist'}), 404

        user_email_hash = create_hash(email)
        data_directory = f"data/{user_email_hash}/{chat['bot_id']}"
        os.makedirs(name=data_directory, exist_ok=True)

        response = s3.list_objects_v2(Bucket=environ.get(
            'S3_BUCKET'), Prefix=data_directory)

        documents = []
        if 'Contents' in response:
            for obj in response.get('Contents', []):
                file_key = obj['Key']
                try:
                    newFileName = f"data/{uuid.uuid4()}"
                    s3.download_file(environ.get('S3_BUCKET'),
                                     file_key, newFileName)

                    if file_key.lower().endswith(".pdf"):
                        loader = PyPDFLoader(newFileName)
                    elif file_key.lower().endswith(".txt"):
                        loader = TextLoader(newFileName)
                    # Use TextLoader to process text content
                    documents += loader.load()
                    os.remove(newFileName)
                except:
                    continue
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=200, chunk_overlap=30)

        texts = text_splitter.split_documents(documents)
        # new_client = chromadb.PersistentClient()
        # persistent_client = chromadb.PersistentClient()
        # persistent_client.create_collection(str(create_hash(email)+str(bot_id)))
        # new_client.create_collection(str(create_hash(email)+str(bot_id)))
        # new_embedding = openai.Embedding.create()
        docsearch = Chroma.from_documents(texts, OpenAIEmbeddings())
        cur.execute(
            'SELECT * FROM chats WHERE email = %s AND bot_name = %s', (email, bot_name))
        chat = cur.fetchone()
        bot_prompt = chat['bot_prompt']

        template = bot_prompt + """
        {context}

        {chat_history}

        Human: {human_input}
        Chatbot: """

        prompt = PromptTemplate(
            template=template,
            input_variables=["chat_history", "human_input", "context"]
        )

        llm = ChatOpenAI(model='gpt-3.5-turbo',
                         streaming=True,
                         callbacks=[StreamingCallBack(uniqueId)],
                         temperature=0)
        memory = ConversationTokenBufferMemory(
            llm=llm, max_token_limit=5000, memory_key="chat_history", input_key="human_input")
        # cursor.execute(
        #     'SELECT * FROM botchain WHERE botid = %s AND email = %s', (bot_id, email,))
        # chain = cursor.fetchone()
        # connection.commit()
        # test a message and log cost of API call

        # if chain is None:
        conversation_chain = load_qa_chain(
            llm=llm, chain_type="stuff", memory=memory, prompt=prompt)
        # else:
        #     chain_memory = chain['chain']
        #     exist_conversation_chain = pickle.loads(bytes(chain_memory))
        #     conversation_chain = load_qa_chain(llm=llm, chain_type="stuff", memory=exist_conversation_chain.memory, prompt=prompt)

        with get_openai_callback() as cb:
            docs = docsearch.similarity_search(query)
            conversation_chain(
                {"input_documents": docs, "human_input": query, "chat_history": ""}, return_only_outputs=True)
            text = conversation_chain.memory.buffer[-1].content

        memory.load_memory_variables({})
        # new_client.delete_collection(str(create_hash(email)+str(bot_id)))
        # new_chain = pickle.dumps(conversation_chain)
        # if chain is None:
        #     cursor.execute('INSERT INTO botchain(email, botid, chain) VALUES (%s, %s, %s) RETURNING *',
        #                 (email, bot_id, new_chain))
        # else:
        #     cursor.execute('UPDATE botchain SET chain = %s WHERE email = %s AND botid = %s', (new_chain, email, bot_id, ))
        # connection.commit()

        # Check if the response contains a link
        url_pattern = re.compile(r"(?P<url>https?://[^\s]+)")

        # replace URLs with anchor tags in the text
        response = url_pattern.sub(
            r"<a href='\g<url>' target='_blank' style='color: #0000FF'>\g<url></a>", text)
        response = response.replace("[", "").replace("]", "")
        response = response.replace("(", "").replace(")", "")
        response = response.rstrip(".")

        # replace URLs with anchor tags in the text
        response = url_pattern.sub(
            r"<a href='\g<url>' target='_blank' style='color: #0000FF'>\g<url></a>", text)

        newMessage = {
            "question": query,
            "answer": response
        }

        cur.execute('SELECT * FROM embedhistory WHERE email = %s AND name = %s AND url = %s',
                    (email, bot_name, uniqueId))
        chat = cur.fetchone()
        now = datetime.now()
        datestr = f"{now}"
        if chat is None:  # create new history
            chatStr = json.dumps([newMessage])
            cursor.execute('INSERT INTO embedhistory(email, name, url, chats, create_time) VALUES (%s, %s, %s, %s, %s)',
                           (email, bot_name, uniqueId, chatStr, datestr))
        else:
            chat_content = chat['chats']
            chat_content.append(newMessage)
            chatStr = json.dumps(chat_content)
            cursor.execute('UPDATE embedhistory set chats = %s, create_time = %s where name = %s and url = %s',
                           (chatStr, datestr, bot_name, uniqueId))
        connection.commit()
        cur.close()
        cursor.close()
        connection.close()

        return jsonify({'message': response}), 200
    except Exception as e:
        print("embed chat error:", str(e))
        return jsonify({'message': 'Bad request'}), 404


@app.get('/api/embed_chat_history')
def get_embed_chat_history():
    # email = request.args.get('email')
    name = request.args.get('bot_name')

    try:
        connection = get_connection()
        cursor = connection.cursor(cursor_factory=extras.RealDictCursor)
        cursor.execute(
            'select * from embedhistory where name = %s order by create_time desc', (name, ))
        chats = cursor.fetchall()
        connection.commit()
        cursor.close()
        connection.close()

        return jsonify({'chats': chats}), 200
    except Exception as e:
        print('get embed chat error:', str(e))
        return jsonify({'message': 'Error while getting embed chat'}), 404


@app.delete('/api/embed_chat_history')
def delete_embed_chat_history():
    id = request.args.get('id')

    try:
        connect = get_connection()
        cursor = connect.cursor(cursor_factory=extras.RealDictCursor)
        cursor.execute('delete from embedhistory where id = %s', (id, ))
        connect.commit()
        cursor.close()
        connect.close()

        return jsonify({'result': 'success'}), 200
    except Exception as e:
        print('delete embed chat history error:', str(e))
        return jsonify({'message': 'Error while getting embed chat'}), 500


@app.post('/api/get_folder_size')
def get_size():
    requestInfo = request.get_json()
    auth_email = requestInfo['email']
    headers = request.headers
    bearer = headers.get('Authorization')
    try:
        token = bearer.split()[1]
        decoded = jwt.decode(token, 'chatsavvy_secret', algorithms="HS256")

        email = decoded['email']

        if (email != auth_email):
            return jsonify({'authentication': False}), 404

        user_email_hash = create_hash(email)
        data_directory = f"data/{user_email_hash}"
        total_size = folder_size(data_directory)
        return jsonify({'size': total_size/1024/1024}), 200
    except Exception as e:
        print("get folder size error:", str(e))
        return jsonify({'message': 'Bad request'}), 404


@app.post('/api/get_pdf_files_name')
def get_pdf_files_name():
    requestInfo = request.get_json()
    auth_email = requestInfo['email']
    bot_id = requestInfo['bot_id']
    headers = request.headers
    bearer = headers.get('Authorization')
    try:
        token = bearer.split()[1]
        decoded = jwt.decode(token, 'chatsavvy_secret', algorithms="HS256")

        email = decoded['email']

        if (email != auth_email):
            return jsonify({'authentication': False}), 404
        user_email_hash = create_hash(email)
        data_directory = f"data/{user_email_hash}/{bot_id}"
        pdf_files = []

        list = s3.list_objects_v2(Bucket=environ.get(
            'S3_BUCKET'), Prefix=data_directory)

        for file in list.get('Contents', []):

            # Check if the file ends with ".pdf" (case-insensitive)
            if file['Key'].lower().endswith(".pdf"):
                # If it does, add the file name to the pdf_files list
                pdf_files.append(file['Key'].split('/')[-1])

        return jsonify({'names': pdf_files})

    except Exception as e:
        print("get pdf file name error:", str(e))
        return jsonify({'message': 'Bad request'}), 404


def delete_pdf_files(data_directory, file_name):
    try:
        # Create the complete path to the file
        # Check if the file exists before attempting to delete it
        s3.delete_object(Bucket=environ.get('S3_BUCKET'),
                         Key=f"{data_directory}/{file_name}")
    except Exception as e:
        print("delete pdf file error:", str(e))


def folder_size(directory):
    def _folder_size(directory):
        total = 0
        list = s3.list_objects_v2(Bucket=environ.get(
            'S3_BUCKET'), Prefix=directory)
        for entry in list.get('Contents', []):
            # for entry in os.scandir(directory):
            if entry['Key'].lower().endswith("/"):
                _folder_size(entry['Key'])
                total += parent_size[entry['Key']]
            else:
                if entry['Key'].lower().endswith('.pdf'):  # Check if file is a PDF
                    size = entry['Size']
                    total += size
                    file_size[entry['Key']] = size
        parent_size[directory] = total

    file_size = {}
    parent_size = {}
    _folder_size(directory)

    return parent_size[directory]

# Serve REACT static files


@app.route('/', methods=['GET'])
def run():
    return 'server is running'


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=False)