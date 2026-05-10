import os
from dotenv import load_dotenv
import google.genai as genai

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key)

with open('screen_test.jpg', 'rb') as f:
    img_data = f.read()

res = client.models.generate_content(
    model='gemini-2.5-flash',
    contents=[
        genai.types.Part.from_bytes(data=img_data, mime_type='image/jpeg'),
        'Tell me exactly what you see in this image. Describe the colors, text, charts, numbers. Is it a totally black screen? Is it empty?'
    ]
)
print("GEMINI SEES:")
print(res.text)
