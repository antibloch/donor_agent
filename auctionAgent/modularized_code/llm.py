import os
from langchain_groq import ChatGroq

def make_model(temperature: float = 0.0):
    return ChatGroq(
        api_key=os.getenv("GROQ_API_KEY"),
        model=os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
        temperature=temperature,
        max_tokens=8192,
    )
