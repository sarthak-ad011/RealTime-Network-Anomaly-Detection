"""Create the `airflow` metadata database on the shared RDS instance.

Piped into the MLflow pod by scripts/install_airflow.sh (`kubectl exec -i`): RDS sits
in a private subnet, and that pod is the only thing in the cluster with both a route
to it and a Postgres driver installed. Reads the connection from the pod's own
BACKEND_URI, so it follows the instance across a destroy/apply cycle.

CREATE DATABASE cannot run inside a transaction, hence autocommit.
"""
import os
from urllib.parse import urlparse

import psycopg2

u = urlparse(os.environ["BACKEND_URI"])
conn = psycopg2.connect(host=u.hostname, port=u.port, user=u.username,
                        password=u.password, dbname="postgres")
conn.autocommit = True
cur = conn.cursor()
cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", ("airflow",))
if cur.fetchone():
    print("airflow database already exists")
else:
    cur.execute("CREATE DATABASE airflow")
    print("created airflow database")
