import openai
import discord
import credentials
from credentials import DALLE_SECRET, OPENAI_API_KEY, DISCORD_TOKEN
import requests
import io
from collections import Counter
import datetime
from tabulate import tabulate
from importlib import import_module
DALLE = import_module("Python-DALLE.DALLE")

dalle = DALLE.DALLE(DALLE_SECRET)
openai.api_key = OPENAI_API_KEY

client = discord.Client()

# Threshold for text moderation
MODERATION_THRESHOLD = 0.1

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

def download_image(image_url: str):
    response = requests.get(image_url)
    
    if response.ok:
        return  io.BytesIO(response.content)
         
    else:
        raise Exception("Error in downloading image from URL")


async def handle_prompt(message: discord.Message):

    # Remove prefix, -generate = 10
    prompt = message.content[10:]
    
    if validate_text(prompt):

        response = await message.reply("Generating...")

        try:
            image_urls = await dalle.generate(prompt)

            image_list = []

            for url in image_urls:
                image_list.append(download_image(url['generation']['image_path']))
            
            cdn_urls = []

            for idx, image in enumerate(image_list): 
                image_id = await message.channel.send(file=discord.File(fp=image, filename=f"{prompt}-{idx+1}.png"))

                cdn_urls.append(image_id.attachments[0].url)

            await response.edit(content="Done!")
            
            # Add prompt to database
            add_prompt(message.author, prompt, serialize_image_urls(cdn_urls), message.created_at)

        except Exception as e:
            await response.edit(content=str(e))
    
    else:
        await message.reply("Your prompt was flagged by the system.")


@client.event
async def on_ready():
    print(f'{client.user} has connected to Discord!')

@client.event
async def on_message(message: discord.Message):

    if message.content.startswith("-generate"):

        handle_prompt(message)


    if message.content.startswith("-dalle"):

        stats = get_stats()

        stats_text = "```"

        stats_text += f"As of {datetime.date.today().strftime('%b %d, %Y')}, total runs: {stats['runs']}, total spent: ${stats['spent']}\n"

        stats_text += "\nStats breakdown\n"


        stats_text += tabulate(stats['user_data'], headers=('User', '# Runs', 'Spent'), tablefmt='fancy_grid')

        stats_text += "```"

        await message.reply(stats_text)

client.run(DISCORD_TOKEN)