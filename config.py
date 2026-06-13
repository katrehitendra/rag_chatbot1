import os
from dotenv import load_dotenv

# Load variables from .env into the system environment
load_dotenv()

class Config:
   
    GROQ_API_KEY = os.getenv('GROQ_API_KEY')
    

    # You can also set a default value if the key is missing
    # API_KEY = os.getenv("MY_API_KEY", "default_key_here")

# Create an instance to be used by other files
settings = Config()