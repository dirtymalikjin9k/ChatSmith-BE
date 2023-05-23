from llama_index import SimpleDirectoryReader, GPTVectorStoreIndex, LLMPredictor, PromptHelper, ServiceContext, GPTKeywordTableIndex, LangchainEmbedding
from llama_index.vector_stores import ChromaVectorStore
from llama_index.storage.storage_context import StorageContext
from langchain import OpenAI
from langchain.embeddings.huggingface import HuggingFaceEmbeddings
import chromadb
import os
import psycopg2
from urllib.parse import urlparse
import re
from os import environ
import hashlib
import json
from dotenv import load_dotenv

load_dotenv()

os.environ["OPENAI_API_KEY"] = environ.get('OPENAI_API_KEY')

chroma_client = chromadb.Client()

host = environ.get('DB_HOST')
port = environ.get('DB_PORT')
dbname = environ.get('DB_NAME')
user = environ.get('DB_USER')
password = environ.get('DB_PASSWORD')


def get_connection():
    conection = psycopg2.connect(host=host,
                        port=port,
                        dbname=dbname,
                        user=user,
                        password=password)
    return conection


def load_index(data_directory):
    if os.path.isfile(f"./{data_directory}/index.json"):
        print("data_directory:", data_directory)
        index = GPTVectorStoreIndex.build_index_from_nodes(
            f"{data_directory}/index.json")
    else:
        print("data_directory=", data_directory)
        from construct_index import construct_index
        index = construct_index(data_directory)
    print("index=", index)
    return index


async def ask_ai(query, data_directory, user_email, bot_id):
    # index = load_index(data_directory)
    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute(
            'SELECT * FROM chats WHERE email = %s AND bot_id = %s ', (user_email, bot_id,))
        chat = cursor.fetchone()
        print("chat = ", chat)
        bot_name = chat['chat_name']
        prompt_base = chat['prompt']

        connection.commit()
        cursor.close()
        connection.close()

        # set number of output tokens
        num_outputs = 512

        # define LLM
        llm_predictor = LLMPredictor(llm=OpenAI(
            temperature=0.7, model_name="text-davinci-003", max_tokens=num_outputs))

        user_email_hash = create_hash(user_email)
        collection_name = f"collection_{user_email_hash}_{bot_id}"
        chroma_collection = chroma_client.get_or_create_collection(
            collection_name)
        embed_model = LangchainEmbedding(HuggingFaceEmbeddings())

        print("count=", chroma_collection.count())

        vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
        storage_context = StorageContext.from_defaults(
            vector_store=vector_store)
        service_context = ServiceContext.from_defaults(
            llm_predictor=llm_predictor, embed_model=embed_model)
        print(storage_context)
        documents = SimpleDirectoryReader(data_directory).load_data()
        index = GPTVectorStoreIndex.from_documents(
                documents, storage_context=storage_context, service_context=service_context)
        
        # index.storage_context.persist(f"{data_directory}/index.json"
        prompt = "Your name is " + bot_name + "." + prompt_base
        print(prompt)
        query_engine = index.as_query_engine()
        response = query_engine.query(prompt + query)
        print("response = ", response.response)
        text = response.response

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
        cur = connection.cursor()
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
    except Exception as e:
        print("Error: " + str(e))
        return "It's no working."


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
        cursor = connection.cursor()        
        cursor.execute("UPDATE chats SET chats = %s WHERE email = %s AND bot_id = %s",
                    (chats_str, user_email, bot_id))
        connection.commit()
        cursor.close()
        connection.close()
        collection_name = f"my_collection_{create_hash(user_email)}_{bot_id}"
        chroma_client.delete_collection(name=collection_name)
        return "ok"
    except:
        return "cant delete"
    
def delete_collection(user_email, connection, cursor):
    try:
        
        cursor.execute("SELECT * FROM chats WHERE email = %s ",
                    (user_email,))
        chats = cursor.fetchall()
        connection.commit()
        
        if(len(chats) > 0):
            for chat in chats:
                collection_name = f"my_collection_{create_hash(user_email)}_{chat['bot_id']}"
                # chroma_client.delete_collection(name=collection_name)

        cursor.execute('DELETE FROM chats WHERE email = %s',
                                (user_email,))
        connection.commit()
        return "ok"
    except:
        return "cant delete"
