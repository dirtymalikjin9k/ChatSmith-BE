from llama_index import SimpleDirectoryReader, GPTVectorStoreIndex, LLMPredictor, PromptHelper, ServiceContext
from llama_index.vector_stores import ChromaVectorStore
from llama_index.storage.storage_context import StorageContext
from langchain import OpenAI
import chromadb
import os
from urllib.parse import urlparse

os.environ["OPENAI_API_KEY"] = "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"

chroma_client = chromadb.Client()

def load_index(data_directory):
    if os.path.isfile(f"./{data_directory}/index.json"):
        print("data_directory:", data_directory)
        index = GPTVectorStoreIndex.build_index_from_nodes(f"{data_directory}/index.json")
    else:
        print("data_directory=",data_directory)
        from construct_index import construct_index
        index = construct_index(data_directory)
    print("index=", index)
    return index

def ask_ai(query, data_directory, bot_id):
    # index = load_index(data_directory)

    collection_name = f"my_collection_{bot_id}"
    chroma_collection = chroma_client.get_or_create_collection(collection_name)
    
    # print(chroma_collection.peek())
    print("count=",chroma_collection.count())

    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    documents = SimpleDirectoryReader(data_directory).load_data()

    print(chroma_collection.count())
    index = GPTVectorStoreIndex.from_documents(documents, storage_context=storage_context)
    # index.storage_context.persist(f"{data_directory}/index.json")
    prompt = "Your name is Arti and you are a very enthusiastic representative of the following website information who loves to help people! You are a live chat ai on this website and people are communicating with you there. Given the following sections of the website, answer the question using only that information and provide a link at the end of your response to a page when it's appropriate. Limit your responses to 50 words. If the topic is unrealted, respond with 'I'm not sure. Can you be more specifc or ask me in a different way?'"
    query_engine = index.as_query_engine(chroma_collection=chroma_collection)
    response = query_engine.query(prompt + query)
    print("response = ",response)
    # Check if the response contains a link
    link_start = response.response.find("http")
    if link_start != -1:
        link_end = response.response.find(" ", link_start)
        if link_end == -1:
            link_end = len(response.response)
        link = response.response[link_start:link_end]
        parsed_link = urlparse(link)

        # Wrap the link in <a> tags if it has a valid scheme and netloc
        if parsed_link.scheme and parsed_link.netloc:
            response.response = response.response[:link_start] + f"<a href='{link}'>{link}</a>" + response.response[link_end:]
    
    return response.response