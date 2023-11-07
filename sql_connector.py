# DB

from pymysql import connect
from sshtunnel import SSHTunnelForwarder
import credentials


class DBClient:

    def __init__(self) -> None:
        self.conn = None
        self.cursor = None


    def initialize(self):
        # start the connection to pythonanywhere
        connection = SSHTunnelForwarder((credentials.ssh_website),
                                        ssh_username=credentials.ssh_username, ssh_password=credentials.ssh_password,
                                        remote_bind_address=(credentials.remote_bind_address, 3306),
                                    ) 
        connection.start()

        # Connect
        self.conn = connect(
            user=credentials.db_user,
            passwd=credentials.db_passwd,
            host=credentials.db_host, port=connection.local_bind_port,
            db=credentials.db,
        )

        self.cursor =  self.conn.cursor()