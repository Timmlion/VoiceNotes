import os
import json
import logging
from typing import List

from fastapi import FastAPI, File, UploadFile, Form
from fastapi.responses import HTMLResponse
import replicate
from dotenv import load_dotenv
import openai

# Set up logging to a file
logging.basicConfig(
    filename='app.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s:%(message)s'
)

# Initialize FastAPI app
app = FastAPI()

# Load environment variables from .env file
load_dotenv()
replicate_api_key = os.getenv("REPLICATE_API_TOKEN")

# Set up the upload folder
UPLOAD_FOLDER = "./uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def transcribe_audio(file_path):
    """
    Transcribe an audio file using Replicate's Whisper model.

    Args:
        file_path (str): The path to the audio file.

    Returns:
        str: The transcribed text.
    """
    try:
        with open(file_path, "rb") as audio_file:
            output = replicate.run(
                "vaibhavs10/incredibly-fast-whisper:3ab86df6c8f54c11309d4d1f930ac292bad43ace52d10c80d87eb258b3c9f79c",
                input={
                    "task": "transcribe",
                    "audio": audio_file,
                    "language": "None",
                    "timestamp": "chunk",
                    "batch_size": 64,
                    "diarise_audio": False
                }
            )
        return output["text"]
    except Exception as e:
        logging.error(f"Error during transcription: {e}")
        return ""

def get_llm_response(transcription, current_document, messages_log):
    """
    Get a response from the LLM based on the transcription,
    current document, and message log.

    Args:
        transcription (str): The transcribed user input.
        current_document (str): The current state of the document.
        messages_log (str): A JSON string representing the conversation history.

    Returns:
        str: The LLM's response.
    """
    api_key = os.getenv('OPENAI_API_KEY')  # Read API key from environment variable
    if not api_key:
        raise ValueError("OpenAI API key is not set in the environment variables.")
    
    openai.api_key = api_key

    # Define the system prompt
    system_prompt = f"""

    **System Prompt:**
    You are an assistant specialized in updating markdown documents. The existing document will be provided in the `<current_document>` block. User input will contain new information or requests to transform the document. Follow these instructions:

    1. Parse and interpret the `<current_document>` block to understand the current state.
    2. Analyze the user message to identify the changes, additions, or transformations required.
    3. Apply the changes to create an updated version of the document.
    4. In your response:
       - Use the `<response>` block to explain what you did, the steps followed, and the reasoning behind your approach.
       - Include the updated markdown document in the `<document>` block.

    **Input Example:**
    ```
    <current_document>
    {current_document}
    </current_document>

    User: Add a new section titled "Section 3" with the content "This is Section 3."
    ```

    **Output Example:**
    ```
    <response>
    I analyzed the current document and identified that a new section titled "Section 3" needed to be added with the specified content. I placed it at the end of the document, consistent with its structure.
    </response>

    <document>
    # My Document
    ## Section 1
    Initial content.

    ## Section 2
    More content here.

    ## Section 3
    This is Section 3.
    </document>
    ```

    **Prompt:**
    You are a markdown document assistant. Given the `<current_document>` and user instructions, modify the document as requested. Explain your changes in the `<response>` block and provide the updated document in the `<document>` block. Maintain markdown formatting and logical structure.

    """

    user_message = transcription

    # Initialize the messages array with the system prompt
    messages = [
        {"role": "system", "content": system_prompt},
    ]

    # Parse messages_log if it's a JSON string
    if isinstance(messages_log, str):
        try:
            messages_log = json.loads(messages_log)
        except json.JSONDecodeError as e:
            logging.error(f"Error parsing messages_log: {e}")
            messages_log = []

    # Add messages_log to messages if it's a valid, non-empty list
    if isinstance(messages_log, list) and messages_log:
        messages += messages_log

    # Add the user's message
    messages.append({"role": "user", "content": user_message})
    logging.info(f"Constructed messages for OpenAI API: {messages}")

    try:
        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages
        )
        return response.choices[0].message.content
    except Exception as e:
        logging.error(f"An error occurred while communicating with OpenAI: {e}")
        return None

def extract_response_and_document(input_string):
    """
    Extract the content within <response> and <document> tags from the input string.

    Args:
        input_string (str): The input string containing <response> and <document> blocks.

    Returns:
        tuple: A tuple containing two strings (response_content, document_content).
    """
    # Extract content between <response> and </response>
    response_start = input_string.find("<response>") + len("<response>")
    response_end = input_string.find("</response>")
    response_content = input_string[response_start:response_end].strip()

    # Extract content between <document> and </document>
    document_start = input_string.find("<document>") + len("<document>")
    document_end = input_string.find("</document>")
    document_content = input_string[document_start:document_end].strip()

    return response_content, document_content

@app.post("/upload/")
async def upload_audio(
    file: UploadFile = File(...),
    note: str = Form(''),
    messages: str = Form('[]')
):
    """
    Endpoint to upload audio, transcribe it, and get an LLM response.

    Args:
        file (UploadFile): The uploaded audio file.
        note (str): The current document content.
        messages (str): The conversation history in JSON string format.

    Returns:
        dict: A dictionary containing the transcription, response, and updated note.
    """
    # Save the uploaded audio file
    file_path = f"{UPLOAD_FOLDER}/{file.filename}"
    with open(file_path, "wb") as buffer:
        buffer.write(await file.read())

    # Process the audio file to get transcription
    transcription = transcribe_audio(file_path)
    logging.info(f"TRANSCRIPTION: {transcription}")

    llm_response = get_llm_response(transcription, note, messages)
    logging.info(f"LLM RESPONSE: {llm_response}")

    if llm_response:
        response, document = extract_response_and_document(llm_response)
    else:
        response, document = "", ""

    return {
        "transcription": transcription,
        "response": response,
        "note": document
    }

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """
    Serve the frontend HTML page.

    Returns:
        HTMLResponse: The index.html content.
    """
    try:
        with open("./static/index.html") as f:
            return f.read()
    except FileNotFoundError:
        logging.error("index.html not found in ./static/ directory.")
        return HTMLResponse(content="<h1>index.html not found</h1>", status_code=404)