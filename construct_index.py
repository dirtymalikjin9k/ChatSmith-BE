from llama_index import SimpleDirectoryReader, GPTVectorStoreIndex, LLMPredictor, PromptHelper, ServiceContext
from llama_index.vector_stores import ChromaVectorStore
from llama_index.storage.storage_context import StorageContext
from langchain import OpenAI
import os
import chromadb
from os import environ

os.environ["OPENAI_API_KEY"] = environ.get('OPENAI_API_KEY')

def construct_index(data_directory):

    chroma_client = chromadb.Client()

    chroma_collection = chroma_client.create_collection("my_collection")

    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    # set maximum input size
    max_input_size = 8191
    # set number of output tokens
    num_outputs = 3000
    # set maximum chunk overlap
    max_chunk_overlap = 50
    # set chunk size limit
    chunk_size_limit = 900
#     define prompt helper
    prompt_helper = PromptHelper(
        max_input_size, num_outputs, max_chunk_overlap, chunk_size_limit=chunk_size_limit)

#     define LLM
    # llm_predictor = LLMPredictor(llm=OpenAI(
    #     temperature=0.5, model_name="text-embedding-ada-002", max_tokens=num_outputs))

    documents = SimpleDirectoryReader(data_directory).load_data()

    # service_context = ServiceContext.from_defaults(
    #     llm_predictor=llm_predictor, prompt_helper=prompt_helper)

    index = GPTVectorStoreIndex.from_documents(documents, storage_context=storage_context)
    # index.storage_context.persist(f"{data_directory}/index.json")
    
    return index
