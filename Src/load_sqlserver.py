# -*- coding: utf-8 -*-
"""📦 Job Skill Analytics - Load to SQL Server Script"""

import boto3
import pandas as pd
import io
import os
import pyodbc

# ---------------- CONFIG ----------------
BUCKET = "job-skill-analytics"
PROCESSED_PREFIX = "transformed/"  # Folder with transformed files
TABLE_NAME = "dbo.job_data"        # Your data table
TRACKER_TABLE = "dbo.etl_loaded_files"  # New tracker table

# ---------------- DB CREDENTIALS ----------------
#based on your setup, consider using environment variables or a secure vault
SQL_SERVER = "your sqlserver hostname or ip"
DATABASE = "yourdatabase"
USERNAME = "yourusername"
PASSWORD = "YourPassword123!"
DRIVER = "{ODBC Driver 18 for SQL Server}"

# ---------------- AWS CLIENT ----------------
s3 = boto3.client("s3")

# ---------------- DATABASE CONNECTION ----------------
def get_sql_connection():
    """Create and return SQL Server connection."""
    conn_str = (
        f"DRIVER={DRIVER};SERVER={SQL_SERVER};DATABASE={DATABASE};"
        f"UID={USERNAME};PWD={PASSWORD};Encrypt=no;TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str)

# ---------------- TRACKER UTILITIES ----------------
def is_file_loaded(file_name):
    """Check if file already exists in the tracker table."""
    conn = get_sql_connection()
    cursor = conn.cursor()
    cursor.execute(f"SELECT 1 FROM {TRACKER_TABLE} WHERE file_name=?", (file_name,))
    result = cursor.fetchone()
    conn.close()
    return result is not None


def mark_file_loaded(file_name):
    """Insert file name into tracker table."""
    conn = get_sql_connection()
    cursor = conn.cursor()
    cursor.execute(f"""
        IF NOT EXISTS (SELECT 1 FROM {TRACKER_TABLE} WHERE file_name=?)
        INSERT INTO {TRACKER_TABLE} (file_name) VALUES (?)
    """, (file_name, file_name))
    conn.commit()
    conn.close()

# ---------------- ETL UTILITIES ----------------
def list_s3_files(prefix):
    """List all CSV files in the S3 processed folder."""
    paginator = s3.get_paginator("list_objects_v2")
    files = []
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".csv"):
                files.append(obj["Key"])
    return files


def append_to_sql(df):
    """Append DataFrame rows into SQL Server table."""
    conn = get_sql_connection()
    cursor = conn.cursor()

    # Clean data
    df = df.where(pd.notnull(df), None)
    for col in ["technical_skills", "soft_skills"]:
        if col in df.columns:
            df[col] = df[col].astype(str)
    df = df.map(lambda x: x.strip() if isinstance(x, str) else x)

    # Dynamic insert builder
    cols = df.columns.tolist()
    placeholders = ", ".join(["?" for _ in cols])
    col_names = ", ".join([f"[{c}]" for c in cols])
    insert_query = f"INSERT INTO {TABLE_NAME} ({col_names}) VALUES ({placeholders})"

    print(f"🧩 Inserting {len(df)} rows with {len(cols)} columns...")
    print(f"➡️ Columns: {cols}")

    cursor.fast_executemany = False   # safer for long strings
    BATCH_SIZE = 100
    for i in range(0, len(df), BATCH_SIZE):
        batch = df.iloc[i:i + BATCH_SIZE]
        cursor.executemany(insert_query, batch.values.tolist())
        conn.commit()

    conn.close()

# ---------------- MAIN EXECUTION ----------------
if __name__ == "__main__":
    print("🔍 Checking for new transformed files in S3...")

    files = list_s3_files(PROCESSED_PREFIX)
    print(f"Found {len(files)} file(s) in {PROCESSED_PREFIX}")

    if not files:
        print("✅ No transformed files found. Exiting.")
    else:
        for file_key in files:
            file_name = os.path.basename(file_key)

            if is_file_loaded(file_name):
                print(f"⏩ Skipping (already loaded): {file_name}")
                continue

            print(f"⬇️ Downloading and loading: {file_name}")
            try:
                # Download from S3
                obj = s3.get_object(Bucket=BUCKET, Key=file_key)
                df = pd.read_csv(io.BytesIO(obj["Body"].read()))

                # Append to SQL Server
                append_to_sql(df)

                # Track as loaded
                mark_file_loaded(file_name)
                print(f"✅ Successfully loaded: {file_name}")

            except Exception as e:
                print(f"❌ Error processing {file_name}: {e}")

    print("🎯 Load pipeline completed.")
