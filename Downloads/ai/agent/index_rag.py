import os
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_ollama import OllamaEmbeddings
from langchain_community.vectorstores import Chroma

DOCS_DIR = "rag_docs"
PERSIST_DIR = "./chroma_db"

def load_documents():
    loader = DirectoryLoader(DOCS_DIR, glob="**/*.md", loader_cls=TextLoader, loader_kwargs={"encoding": "utf-8"})
    docs = loader.load()
    print(f"Загружено {len(docs)} документов")
    return docs

def split_documents(docs):
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = splitter.split_documents(docs)
    print(f"Создано {len(chunks)} чанков")
    return chunks

def create_vectorstore(chunks):
    embeddings = OllamaEmbeddings(model="llama3.2:3b", base_url=os.getenv("OLLAMA_BASE_URL", "http://ollama:11434"))
    vectorstore = Chroma.from_documents(chunks, embeddings, persist_directory=PERSIST_DIR)
    vectorstore.persist()
    print(f"Векторная БД сохранена в {PERSIST_DIR}")

if __name__ == "__main__":
    docs = load_documents()
    chunks = split_documents(docs)
    create_vectorstore(chunks)