import io
from tabulate import tabulate
import openai
import requests
import discord
from PIL import Image

# Threshold for text moderation
MODERATION_THRESHOLD = 0.25

# Threshold for image size in variations
IMAGE_SIZE_LIMIT_IN_BYTES = 4 * 1024 * 1024

def validate_text(text):
    response = openai.moderations.create(input=text)

    output = response.results[0]

    for category in output.category_scores:
        value = category[1]

        if value >= MODERATION_THRESHOLD:

            return False

    return not output.flagged

def download_image(image_url: str) -> io.BytesIO:
    response = requests.get(image_url)
    
    if response.ok:
        return  io.BytesIO(response.content)
         
    else:
        raise Exception("Error in downloading image from URL")
    
def serialize_image_urls(images_urls: list):
    return "|".join(images_urls)

async def get_discord_image_from_message(message: discord.Message) -> io.BytesIO:
    image_io = io.BytesIO()
    await message.attachments[0].save(image_io)
    image_io.seek(0)
    return image_io

async def preprocess_input_image(image_io: io.BytesIO):
    # Flag to tell if image was resized
    resized = False

    image = Image.open(image_io)

    width, height = image.size

    if width != height:
        new_size = min(width, height)
        resized = f"Input image is {width}x{height} when it needs to be 1:1. I resized it for you so that it is {new_size}x{new_size}. Will continue generating..."
        image = image.resize((new_size, new_size), resample=Image.Resampling.NEAREST)
    
    new_image_io = io.BytesIO()
    image.save(new_image_io, format="PNG")
    new_image_io.seek(0)

    image_bytes_size = new_image_io.getbuffer().nbytes
    if  image_bytes_size >= IMAGE_SIZE_LIMIT_IN_BYTES:
        resized = f"Input image is {round(image_bytes_size/(1024*1024), 2)} MBs when it needs to be less than 4 MBs. I cropped it to 500x500 to reduce size. Will continue generating..."
        image = image.resize((500, 500), resample=Image.Resampling.NEAREST)
        new_image_io = io.BytesIO()
        image.save(new_image_io, format="PNG", quality=95)
        new_image_io.seek(0)

    return new_image_io, resized

async def send_dalle_images(dalle_response, message: discord.Message, prompt):
    # Create list of download images from dalle urls
    image_list = [download_image(img.url) for img in dalle_response.data]

    cdn_urls = []

    for idx, image in enumerate(image_list): 
        image_id = await message.channel.send(file=discord.File(fp=image, filename=f"{prompt}-{idx+1}.png"))
        cdn_urls.append(image_id.attachments[0].url)

    return cdn_urls
