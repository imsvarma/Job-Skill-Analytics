# -*- coding: utf-8 -*-
"""📦 Job Skill Analytics - Data Transformation Script"""

import boto3
import pandas as pd
import io
import re
import logging
from datetime import datetime

# ------------------- CONFIG ---------------------------
BUCKET = "job-skill-analytics"
RAW_PREFIX = "extract/raw/"         # <-- change if your folder name differs
PROCESSED_PREFIX = "transformed/"
LOG_FILE = "s3_transform_pipeline.log"
FORCE_REPROCESS = False  # ✅ set True to force all files to reprocess

# Setup logging
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# ------------------- AWS CLIENT -----------------------
s3 = boto3.client("s3")

# ------------------- UTILITIES ------------------------
def list_s3_files(prefix):
    """List all CSV files under a given prefix."""
    paginator = s3.get_paginator("list_objects_v2")
    page_iterator = paginator.paginate(Bucket=BUCKET, Prefix=prefix)
    files = []
    for page in page_iterator:
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".csv"):
                files.append(obj["Key"])
    return files


def infer_job_type(row):
    """Infer job type from job_type + job_title combined."""
    jt = str(row.get("job_type", "")).lower()
    title = str(row.get("job_title", "")).lower()
    text = f"{jt} {title}"

    types = set()
    if re.search(r"full[- ]?time", text):
        types.add("Full-Time")
    if re.search(r"part[- ]?time", text):
        types.add("Part-Time")
    if re.search(r"contract", text):
        types.add("Contract")
    if re.search(r"intern|internship", text):
        types.add("Internship")
    if re.search(r"temp|temporary", text):
        types.add("Temporary")
    if re.search(r"freelance|consult", text):
        types.add("Freelance")

    return ", ".join(sorted(types)) if types else "Not specified"


def clean_job_title(title):
    """Simplify and standardize job titles."""
    if not isinstance(title, str):
        return title

    # Lowercase for uniform cleaning
    t = title.lower()

    # Remove content inside brackets or parentheses
    t = re.sub(r"\(.*?\)|\[.*?\]|\{.*?\}", "", t)

    # Remove everything after -, #, |, /
    t = re.split(r"[-#|/]", t)[0]

    # Remove roman numerals (I, II, III, IV, etc.)
    t = re.sub(r"\b[ivx]+\b", "", t)

    # Remove seniority & unnecessary words
    t = re.sub(
        r"\b(senior|sr|junior|jr|lead|principal|chief|head|manager|director|vp|vice president|president|internship|intern|contract|temp|temporary|remote|hybrid|hiring|immediate joiner|via|through)\b",
        "",
        t,
    )

    # Remove special characters and extra spaces
    t = re.sub(r"[^a-zA-Z\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()

    # Capitalize properly
    return t.title()


def transform_data(df):
    """Perform full cleaning & normalization."""
    # ---- Data type conversions ----
    if "job_posted_date" in df.columns:
        df["job_posted_date"] = pd.to_datetime(df["job_posted_date"], errors="coerce")
    if "salary" in df.columns:
        df["salary"] = pd.to_numeric(df["salary"], errors="coerce")

    # ---- Text cleanup ----
    text_cols = ["company_name", "job_title", "job_type", "job_location", "job_posted_site"]
    for col in text_cols:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip().str.lower()

    # ---- Clean and simplify job titles ----
    if "job_title" in df.columns:
        df["job_title"] = df["job_title"].apply(clean_job_title)

    # ---- Infer job type intelligently ----
    df["job_type"] = df.apply(infer_job_type, axis=1)

    # ---- Handle missing values ----
    df.fillna({
        "company_name": "Unknown",
        "technical_skills": "not listed",
        "soft_skills": "not listed"
    }, inplace=True)

    # ---- Parse & flatten skills ----
    if "technical_skills" in df.columns:
        df["technical_skills"] = df["technical_skills"].apply(
            lambda x: ", ".join([i.strip().lower() for i in x.split(",") if i.strip()]) if isinstance(x, str) else "not listed"
        )
    if "soft_skills" in df.columns:
        df["soft_skills"] = df["soft_skills"].apply(
            lambda x: ", ".join([i.strip().lower() for i in x.split(",") if i.strip()]) if isinstance(x, str) else "not listed"
        )

    # ---- Drop duplicates ----
    df.drop_duplicates(subset=["company_name", "job_title", "job_location", "job_posted_site"], inplace=True)

    # ---- Filter salary outliers ----
    if "salary" in df.columns:
        df = df[(df["salary"] >= 20000) & (df["salary"] <= 400000)]

    # ---- Derived columns ----
    if "job_posted_date" in df.columns:
        df["job_posted_year"] = df["job_posted_date"].dt.year
    if "job_location" in df.columns:
        df["city"] = df["job_location"].apply(lambda x: x.split(",")[0].strip() if isinstance(x, str) and "," in x else x)

    return df


def process_file(file_key):
    """Download → transform → upload to processed folder."""
    logging.info(f"Processing file: {file_key}")
    try:
        obj = s3.get_object(Bucket=BUCKET, Key=file_key)
        df = pd.read_csv(io.BytesIO(obj["Body"].read()))

        df_transformed = transform_data(df)

        # Generate processed key (same name, different folder)
        output_key = file_key.replace(RAW_PREFIX, PROCESSED_PREFIX)

        buffer = io.StringIO()
        df_transformed.to_csv(buffer, index=False)
        s3.put_object(Bucket=BUCKET, Key=output_key, Body=buffer.getvalue().encode("utf-8"))

        logging.info(f"✅ Uploaded processed file: {output_key}")
        print(f"✅ Uploaded: {output_key}")

    except Exception as e:
        logging.error(f"❌ Error processing {file_key}: {e}")
        print(f"❌ Error processing {file_key}: {e}")


# ------------------- MAIN EXECUTION -------------------
if __name__ == "__main__":
    print("🔍 Checking for new raw files on S3...")

    raw_files = list_s3_files(RAW_PREFIX)
    processed_files = list_s3_files(PROCESSED_PREFIX)

    print(f"Raw files found: {len(raw_files)}")
    print(f"Processed files found: {len(processed_files)}")

    # Determine which raw files have not been processed
    if FORCE_REPROCESS:
        new_files = raw_files
        print("⚠️ FORCE_REPROCESS=True — all files will be reprocessed.")
    else:
        processed_set = set(processed_files)
        new_files = [
            f for f in raw_files
            if f.replace(RAW_PREFIX, PROCESSED_PREFIX) not in processed_set
        ]

    print(f"🆕 Files to process: {len(new_files)}")

    if not new_files:
        print("✅ No new unprocessed files found. Exiting.")
        logging.info("No new unprocessed files found.")
    else:
        for file_key in new_files:
            print(f"🚀 Processing {file_key}...")
            process_file(file_key)

    print("🎯 Pipeline completed.")
