import json
import os
import logging
from datetime import datetime, timezone

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    """
    AWS Lambda handler triggered by SQS events.
    Reads batches of ArticleIn payload and writes them to RDS PostgreSQL databases.
    Requires psycopg2-binary installed in the Lambda environment or as a Layer.
    """
    import psycopg2

    rds_host = os.environ.get('RDS_HOST')
    db_name = os.environ.get('DB_NAME')
    db_user = os.environ.get('DB_USER')
    db_pass = os.environ.get('DB_PASSWORD')

    if not all([rds_host, db_name, db_user, db_pass]):
        logger.error("Missing Database credentials in environment variables.")
        raise ValueError("Missing database environment variables.")

    conn = psycopg2.connect(
        host=rds_host, 
        database=db_name,
        user=db_user, 
        password=db_pass,
        sslmode='require' # Secure RDS connection
    )
    
    total_processed = 0

    try:
        with conn.cursor() as cursor:
            # We process each message in the batch provided by SQS
            for record in event.get('Records', []):
                try:
                    payload_list = json.loads(record['body'])
                    # Loop over all items batched inside the single SQS message
                    inserted_now = 0
                    skipped_now = 0
                    for item in payload_list:
                        # item keys: source, canonical_url, title, summary, published_at
                        source = item.get("source")
                        canonical_url = item.get("canonical_url")
                        title = item.get("title")
                        summary = item.get("summary")
                        published_at = item.get("published_at") # ISO format string or None
                        fetched_at = datetime.now(timezone.utc).isoformat()
                        
                        # Check exist
                        cursor.execute("SELECT id FROM articles WHERE canonical_url = %s", (canonical_url,))
                        if cursor.fetchone():
                            skipped_now += 1
                            continue
                            
                        # Insert
                        cursor.execute(
                            """
                            INSERT INTO articles (source, canonical_url, title, summary, published_at, fetched_at)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            """,
                            (source, canonical_url, title, summary, published_at, fetched_at)
                        )
                        inserted_now += 1
                    
                    logger.info(f"SQS Message processed. Inserted: {inserted_now}. Skipped: {skipped_now}.")
                    total_processed += inserted_now
                except Exception as e:
                    logger.error(f"Error handling individual SQS record: {e}. Record: {record}")
                    raise e
                    
        # Commit the transaction once all records in the Lambda invocation are processed
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Transaction failed, changes rolled back: {e}")
        raise e
    finally:
        conn.close()

    return {
        'statusCode': 200,
        'body': json.dumps({'message': 'Success', 'inserted': total_processed})
    }
