import os
from psycopg2 import connect, extras
import re
from os import environ
import hashlib
import json
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

load_dotenv()

if environ.get('OPENAI_API_KEY') is not None:
    os.environ["OPENAI_API_KEY"] = environ.get('OPENAI_API_KEY')

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


async def ask_ai(query, data_directory, user_email, bot_id):
    print("data_directory ==",data_directory)
    # documents = SimpleDirectoryReader(data_directory).load_data()

    loader = DirectoryLoader(data_directory, glob="./*.txt", loader_cls=TextLoader)
    documents = loader.load()

    print("documents = ", documents)

    # Split and diveide text to prepare embeddings
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=50)   

    # texts = text_splitter.split_documents(documents)

    # #preview one of the texts that has been split. For testing only
    # texts[0]

    # #preview the number of documents that was split. For testing only
    # len(texts)

    # create the embeddings
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
    html_text = url_pattern.sub(
        r"<a href='\g<url>' target='_blank' style='color: #0000FF'>\g<url></a>", text)

    newMessage = {
        "question": query,
        "answer": html_text
    }

    connection = get_connection()
    cur = connection.cursor(cursor_factory=extras.RealDictCursor)
    cur.execute(
        'SELECT * FROM chats WHERE email = %s AND bot_id = %s', (user_email, bot_id))
    chat = cur.fetchone()
    chat_content = chat['chats']
    chat_content.append(newMessage)
    print(chat_content)
    updated_json_data_string = json.dumps(chat_content)
    cur.execute("UPDATE chats SET chats = %s WHERE email = %s AND bot_id = %s",
                (updated_json_data_string, user_email, bot_id))
    connection.commit()
    cur.close()
    connection.close()
    # return the converted text with HTML anchor tags
    return html_text
    # return "ok"




def create_hash(text):
    return hashlib.md5(text.encode()).hexdigest()


def delete_data_collection(user_email, bot_id):
    try:
        chats = [{
            "question": "",
            "answer": ""
        }]
        chats_str = json.dumps(chats)
        print(chats_str)
        connection = get_connection()
        cursor = connection.cursor(cursor_factory=extras.RealDictCursor)        
        cursor.execute("UPDATE chats SET chats = %s WHERE email = %s AND bot_id = %s",
                    (chats_str, user_email, bot_id))
        connection.commit()
        cursor.close()
        connection.close()
        # collection_name = f"my_collection_{create_hash(user_email)}_{bot_id}"
        # chroma_client.delete_collection(name=collection_name)
        return "ok"
    except:
        return "cant delete"
    
def delete_collection(user_email, connection, cursor):
    try:
        
        cursor.execute("SELECT * FROM chats WHERE email = %s ",
                    (user_email,))
        connection.commit()
        
        # if(len(chats) > 0):
        #     for chat in chats:
        #         collection_name = f"my_collection_{create_hash(user_email)}_chat['bot_id']}"
        #         # chroma_client.delete_collection(name=collection_name)

        cursor.execute('DELETE FROM chats WHERE email = %s',
                                (user_email,))
        connection.commit()
        return "ok"
    except:
        return "cant delete"
