from airflow import DAG
from airflow.operators.bash import BashOperator
from datetime import datetime, timedelta
import pendulum

local_tz = pendulum.timezone("America/New_York")
# =========================================================
# ⚙️ Default Configuration
# =========================================================
default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=3),
}

# =========================================================
# 📅 DAG Definition
# =========================================================
with DAG(
    dag_id="job_pipeline_full_dag",
    default_args=default_args,
    description="Full ETL pipeline running sample_test → extract → load_sqlserver",
    schedule_interval="0 9 * * *",  # ✅ every day at 9:00 AM
    start_date=datetime(2025, 10, 1, tzinfo=local_tz),
    catchup=False,
    tags=["etl", "aws", "sqlserver", "pipeline"]
) as dag:

    # ---------- ✅ TASK 1: Verify Environment Variables ----------
    check_env = BashOperator(
        task_id="check_env_vars",
        bash_command="""
        echo "🔍 Checking Environment Variables..."
        echo "OPENAI_API_KEY: ${OPENAI_API_KEY:0:8}********"
        echo "AWS_ACCESS_KEY_ID: ${AWS_ACCESS_KEY_ID:0:4}********"
        echo "AWS_REGION: ${AWS_DEFAULT_REGION}"
        """,
    )

    # ---------- TASK 2: Install dependencies ----------
    install_deps = BashOperator(
        task_id="install_dependencies",
        bash_command="pip install -r /opt/airflow/dags/repo/requirements.txt --quiet"
    )

    # ---------- TASK 3: Run sample_test.py ----------
    data_extraction = BashOperator(
        task_id="data_extraction",
        bash_command="python /opt/airflow/dags/repo/src/data_extract.py"
    )

    # ---------- TASK 5: Run load_sqlserver.py ----------
    data_load = BashOperator(
        task_id="run_load_sqlserver",
        bash_command="python /opt/airflow/dags/repo/src/load_sqlserver.py"
    )

    # ---------- TASK 6: Final confirmation ----------
    post_check = BashOperator(
        task_id="post_check",
        bash_command="echo '✅ Pipeline completed successfully — check S3 and SQL Server tables!'"
    )

    # =========================================================
    # 🔁 TASK ORDER
    # =========================================================
    # ---------- TASK 4: Run transform.py ----------
    data_transformation = BashOperator(
        task_id="run_transform",
        bash_command="python /opt/airflow/dags/repo/src/transform.py"
    )



    check_env >> install_deps >>  data_extraction >> data_transformation >> data_load >> post_check
