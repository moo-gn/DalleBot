import io
import datetime
import logging
from urllib.parse import urlparse
from collections import Counter
from tabulate import tabulate
import openai
import discord
from discord.ext import commands
from discord import Intents
import credentials
from sql_connector import DBClient
from helpers import *

logging.getLogger().setLevel(logging.INFO)

openai.api_key = credentials.OPENAI_API_KEY

client = discord.Client(intents=Intents.all())

bot = commands.Bot(intents=Intents.all(), command_prefix='-')

db_client = DBClient()

# Enable this flag if you want to store results in a remote database
USE_DB_FLAG = True

DEBUG = False

FLAGS_PREFIX = "--"


class GenerateFlags(commands.FlagConverter, delimiter=' ', prefix=FLAGS_PREFIX): # To be integrated later
    quality: str = commands.flag(name='quality', aliases=['q'], default='hd')
    n: int = commands.flag(name='n', default=1)

@bot.command(aliases=["g"])
async def generate(ctx, *args):
    prompt = " ".join(args)
    await generate_route(ctx.message, prompt)

@bot.command(aliases=["v"])
async def variation(ctx):
    await variations_route(ctx.message)

@bot.command(aliases=["d"])
async def dalle(ctx):
    await dalle_route(ctx.message)


def add_prompt(author, prompt, image_urls, timestamp):

    sql = "INSERT INTO dalle(author, prompt, image_urls, timestamp) values (%s, %s, %s, %s);"
    val = (author, prompt, image_urls, timestamp)

    try:
        db_client.cursor.execute(sql, val)
        db_client.conn.commit()

    except Exception as err:
        # Refresh connection for next entry
        logging.warning(err)
        db_client.initialize()
        raise


def get_stats():

    stats = {}

    db_client.cursor.execute("SELECT COUNT(*) FROM dalle;")

    data = db_client.cursor.fetchone()

    stats['runs'] = data[0]

    stats['spent'] = round(15.0/115.0 * stats['runs'], 2)

    db_client.cursor.execute(f"SELECT author FROM dalle;")

    data = db_client.cursor.fetchall()
    
    user_counts = Counter(data)

    user_data = [] 

    for user, count in user_counts.items():
        val = (user[0], count, f"${round(15.0/115.0 * count, 2)}")
        user_data.append(val)

    user_data.sort(key=lambda x: x[1], reverse=True)

    stats['user_data'] = user_data

    return stats


async def generate_route(message: discord.Message, prompt: str):
    
    if validate_text(prompt):

        bot_response = await message.reply("Generating...")

        try:
            dalle_response = openai.images.generate(
                model="dall-e-3",
                prompt=prompt,
                n=1,
                size="1024x1024",
                quality="hd",
                response_format="url"
            )
        except Exception as error:
            await bot_response.edit(content=error)
            return error


        cdn_urls = await send_dalle_images(dalle_response, message, prompt)

        await bot_response.edit(content="Done!")

        # Add prompt to database
        if not USE_DB_FLAG:
            return "success"

        try:
            add_prompt(message.author, prompt, serialize_image_urls(cdn_urls), message.created_at)
        except Exception as error:
            await bot_response.edit(content="Done, but can't store image in database due to an error.")
            return error

        return "success"
    
    # If failed first validation or second validation
    await message.reply("Your prompt was flagged by the system.")
    return "failed"


async def variations_route(message: discord.Message):    

    # In case the image is in a reply and not direct attachment
    if message.reference is not None:
        message = await message.channel.fetch_message(message.reference.message_id) 

    # The image is a url not an attachment
    if not message.attachments:
        # Check url is valid
        try: 
            urlparse(message.content)
        except:
            message.reply("Can't download image from URL, url is invalid.")
            return

        image_io = download_image(message.content)
        prompt = f"variation of image {message.content}"


    else:
        image_io = await get_discord_image_from_message(message)
        prompt = f"variation of image {message.attachments[0].filename}"


    try:
        image, resized = await preprocess_input_image(image_io)
    except Exception as error:
        await message.reply("Couldn't process the file, are you sure it's an image?")
        return

    if resized and DEBUG:
        await message.reply(resized)
        await message.channel.send(file=discord.File(fp=image, filename=f"{message.id}.png"))

    try:
        bot_response = await message.reply("Generating...")
        dalle_response = openai.images.create_variation(
            model="dall-e-2",
            image=image.getvalue(),
            n=4,
            size="1024x1024",
            response_format="url"
        )
    except Exception as error:
        await bot_response.edit(content=error)
        return error


    cdn_urls = await send_dalle_images(dalle_response, message, prompt)

    await bot_response.edit(content="Done!")

    if not USE_DB_FLAG:
        return "success"
    # Add prompt to database
    try:
        add_prompt(message.author, prompt, serialize_image_urls(cdn_urls), message.created_at)
    except Exception as error:
        await bot_response.edit(content="Done, but can't store image in database due to an error.")
        return error

    return "success"
    

async def dalle_route(message: discord.Message):

    stats = get_stats()

    stats_text = "```"

    stats_text += f"As of {datetime.date.today().strftime('%b %d, %Y')}, total runs: {stats['runs']}, total spent: ${stats['spent']}\n"

    stats_text += "\nStats breakdown\n"

    stats_text += tabulate(stats['user_data'], headers=('User', '# Runs', 'Spent'), tablefmt='fancy_grid')

    stats_text += "```"

    # await message.reply(stats_text)

    # If reply exceeds 2000 chars, split it into multiple messages each of size 2000 chars
    if len(stats_text) > 2000:
        for i in range(0, len(stats_text), 2000):
            await message.reply(stats_text[i:i+2000])
    else:
        await message.reply(stats_text)



@bot.event
async def on_ready():
    logging.info(f'{bot.user} has connected to Discord!')


bot.run(credentials.DISCORD_TOKEN)