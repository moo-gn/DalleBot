from urllib import response
import openai
import discord
from credentials import DALLE_SECRET, OPENAI_API_KEY, DISCORD_TOKEN
# import urllib.request
import requests
import io
from importlib import import_module
DALLE = import_module("Python-DALLE.DALLE")

dalle = DALLE.DALLE(DALLE_SECRET)
openai.api_key = OPENAI_API_KEY

client = discord.Client()

# Threshold for text moderation
MODERATION_THRESHOLD = 0.1

def validate_text(text):

    response = openai.Moderation.create(input=text)

    output = response["results"][0]

    for category, value in output['category_scores'].items():

        if value >= MODERATION_THRESHOLD:

            return False

    return not output["flagged"]

def download_image(image_url: str):
    response = requests.get(image_url)
    
    if response.ok:
        return  io.BytesIO(response.content)
         
    else:
        raise Exception("Error in downloading image from URL")



@client.event
async def on_ready():
    print(f'{client.user} has connected to Discord!')

@client.event
async def on_message(message: discord.Message):
    
    message_text = str(message.content)

    if message_text.startswith("-generate"):

        dalle_prompt = message_text[10:]

        if validate_text(dalle_prompt):

            response = await message.reply("Generating...")

            try:
                image_urls = await dalle.generate(dalle_prompt)

                image_list = []

                for url in image_urls:
                    image_list.append(download_image(url['generation']['image_path']))

                for idx, image in enumerate(image_list): 
                    await message.channel.send(file=discord.File(fp=image, filename=f"{dalle_prompt}-{idx+1}.png"))

                await response.edit(content="Done!")

            except Exception as e:
                await response.edit(content=str(e))

        else:
            await message.reply("Your prompt was flagged by the system.")

client.run(DISCORD_TOKEN)