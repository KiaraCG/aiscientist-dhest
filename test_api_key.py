import os
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables from the .env file
load_dotenv()

# Initialize the OpenAI client pointing to the CSCS Inference API base URL
client = OpenAI(
    base_url="https://api.inference.cscs.ch/v1",
    api_key=os.environ.get("CSCS_INFERENCE_API_KEY")
)

try:
    # Test the API key with a simple chat completion request
    response = client.chat.completions.create(
        model="CSCS-Inference/google/gemma-4-31B-it",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello! Reply with 'API key works!' if you can read this."}
        ],
        max_tokens=50
    )
    
    print("Connection successful!")
    print("Response from model:")
    print(response.choices[0].message.content)

except Exception as e:
    print("An error occurred while testing the API key:")
    print(e)
