import io
import openai
import discord
from PIL import Image
import credentials
from credentials import OPENAI_API_KEY, DISCORD_TOKEN
import requests
import io
from collections import Counter
import datetime
from tabulate import tabulate
from importlib import import_module
from urllib.parse import urlparse

openai.api_key = OPENAI_API_KEY

client = discord.Client()

# Flag for debugging
DEBUG = False


# Threshold for text moderation
MODERATION_THRESHOLD = 0.1

# Threshold for image size in variations
IMAGE_SIZE_LIMIT_IN_BYTES = 4 * 1024 * 1024

# DB
from pymysql import connect
from sshtunnel import SSHTunnelForwarder

# start the connection to pythonanywhere
connection = SSHTunnelForwarder((credentials.ssh_website),
                                ssh_username=credentials.ssh_username, ssh_password=credentials.ssh_password,
                                remote_bind_address=(credentials.remote_bind_address, 3306),
                             ) 
connection.start()


def db_init():
  """
  Connects to the remote database, returns the database and its cursor
  """
  # Connect
  db = connect(
      user=credentials.db_user,
      passwd=credentials.db_passwd,
      host=credentials.db_host, port=connection.local_bind_port,
      db=credentials.db,
  )

  # Return cursor and db
  return db.cursor(), db 


def serialize_image_urls(images_urls: list):
    return "|".join(images_urls)


def add_prompt(author, prompt, image_urls, timestamp):

    cursor, db = db_init()

    sql = "INSERT INTO dalle(author, prompt, image_urls, timestamp) values (%s, %s, %s, %s);"
    val = (author, prompt, image_urls, timestamp)

    cursor.execute(sql, val)

    db.commit()

    db.close()


def get_stats():

    cursor, db = db_init()

    stats = {}

    cursor.execute("SELECT COUNT(*) FROM dalle;")

    data = cursor.fetchone()

    stats['runs'] = data[0]

    stats['spent'] = round(15.0/115.0 * stats['runs'], 2)

    cursor.execute(f"SELECT author FROM dalle;")

    data = cursor.fetchall()

    db.close()
    
    user_counts = Counter(data)

    user_data = [] 

    for user, count in user_counts.items():
        val = (user[0], count, f"${round(15.0/115.0 * count, 2)}")
        user_data.append(val)

    user_data.sort(key=lambda x: x[1], reverse=True)

    stats['user_data'] = user_data

    return stats


def validate_text(text):
    response = openai.Moderation.create(input=text)

    output = response["results"][0]

    for category, value in output['category_scores'].items():

        if value >= MODERATION_THRESHOLD:

            return False

    return not output["flagged"]


def download_image(image_url: str) -> io.BytesIO:
    response = requests.get(image_url)
    
    if response.ok:
        return  io.BytesIO(response.content)
         
    else:
        raise Exception("Error in downloading image from URL")


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
    image_list = [download_image(url["url"]) for url in dalle_response["data"]]

    cdn_urls = []

    for idx, image in enumerate(image_list): 
        image_id = await message.channel.send(file=discord.File(fp=image, filename=f"{prompt}-{idx+1}.png"))
        cdn_urls.append(image_id.attachments[0].url)

    return cdn_urls

async def generate_route(message: discord.Message):
    # Removes prefix "-generate"
    prompt = message.content[10:]
    
    if validate_text(prompt):

        bot_response = await message.reply("Generating...")

        try:
            dalle_response = openai.Image.create(
                api_key=OPENAI_API_KEY,
                prompt=prompt,
                n=4,
                size="1024x1024",
                response_format="url"
            )
        except Exception as error:
            await bot_response.edit(content=error)
            return error


        cdn_urls = await send_dalle_images(dalle_response, message, prompt)

        await bot_response.edit(content="Done!")

        # Add prompt to database
        try:
            add_prompt(message.author, prompt, serialize_image_urls(cdn_urls), message.created_at)
        except Exception as error:
            print(error)
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
        dalle_response = openai.Image.create_variation(
            api_key=OPENAI_API_KEY,
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

    # Add prompt to database
    try:
        add_prompt(message.author, prompt, serialize_image_urls(cdn_urls), message.created_at)
    except Exception as error:
        print(error)
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

    await message.reply(stats_text)


@client.event
async def on_ready():
    print(f'{client.user} has connected to Discord!')


@client.event
async def on_message(message: discord.Message):

    if message.content.startswith("-generate"):
        await generate_route(message)


    if message.content.startswith("-dalle"):
        await dalle_route(message)


    if message.content.startswith("-variation") or message.content.startswith("-v"):
        await variations_route(message)


client.run(DISCORD_TOKEN)