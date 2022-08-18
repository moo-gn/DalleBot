import DALLE
import openai
import discord
from credentials import SECRET, API_KEY, TOKEN

dalle = DALLE.DALLE(SECRET)
openai.api_key = API_KEY

client = discord.Client()

# Threshold for text moderation
MODERATION_THRESHOLD = 0.1

def validate_text(text):

    response = openai.Moderation.create(input=text)

    output = response["results"][0]

    for category, value in output['category_scores'].items():

        if value >= MODERATION_THRESHOLD:

            return False

    return True

@client.event
async def on_ready():
    print(f'{client.user} has connected to Discord!')

@client.event
async def on_message(message: discord.Message):
    
    message_text = str(message.content)

    if message_text.startswith("-generate"):

        dalle_prompt = message_text.removeprefix("-generate")

        if validate_text(dalle_prompt):

            print(dalle_prompt)

            response = await message.reply("Generating...")

            images = await dalle.generate(dalle_prompt)

            try:
                for img in images:
                    await message.reply(img['generation']['image_path'])

                await response.edit(content="Done!")

            except TypeError:
                response.edit(content="Your prompt was flagged by the system.")

        else:
            message.reply("Your prompt was flagged by the system.")

client.run(TOKEN)