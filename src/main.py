import os
import json
import streamlit as st
from groq import Groq
import sqlite3
import re  # For regex operations

# Streamlit page configuration
st.set_page_config(
    page_title="Text2SQL Chatbot",
    page_icon="💻",
    layout="centered"
)

# Load GROQ API Key from Streamlit secrets
GROQ_API_KEY = st.secrets["groq"]["GROQ_API_KEY"]

# Save API key to environment variable
os.environ["GROQ_API_KEY"] = GROQ_API_KEY

# Initialize Groq client
client = Groq()

# Define the path to your SQLite database
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, 'data', 'chinook.db')

# Establish SQLite connection with cached resource for efficiency
@st.cache_resource
def init_sqlite(db_path):
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row  # Enable dictionary-like cursor
    return conn

conn = init_sqlite(DATABASE_PATH)

# Function to extract database schema dynamically
def get_database_schema(conn):
    schema = ""
    cursor = conn.cursor()

    # Fetch all table names excluding SQLite's internal tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
    tables = cursor.fetchall()

    for table in tables:
        table_name = table[0]
        schema += f"Table: {table_name}\n"

        # Fetch columns for each table
        cursor.execute(f"PRAGMA table_info({table_name});")
        columns = cursor.fetchall()

        for column in columns:
            col_id, col_name, col_type, notnull, default_value, is_pk = column
            schema += f"  - {col_name} ({col_type})\n"

        # Fetch foreign keys for each table
        cursor.execute(f"PRAGMA foreign_key_list({table_name});")
        fkeys = cursor.fetchall()
        for fkey in fkeys:
            id, seq, table_fk, from_col, to_col, on_update, on_delete, match = fkey
            schema += f"  - Foreign Key: {from_col} references {table_fk}({to_col})\n"

        schema += "\n"

    return schema

# Function to clean the SQL query by removing markdown syntax
def clean_sql_query(raw_response):
    """
    Removes markdown code blocks and other extraneous characters from the SQL query.
    """
    # Remove ```sql and ``` markers if present
    sql_query = re.sub(r"```sql", "", raw_response, flags=re.IGNORECASE)
    sql_query = re.sub(r"```", "", sql_query)
    
    # Remove any leading/trailing whitespace
    sql_query = sql_query.strip()
    
    return sql_query

# Function to convert text input to SQL query using Llama with schema context
def text_to_sql(user_input, conn):
    # Retrieve the current database schema
    schema = get_database_schema(conn)

    # Create a detailed prompt including the schema
    prompt = f"""
You are an SQL assistant. Below is the schema of the SQLite database:

{schema}

Convert the following natural language request into a valid SQL query that can be executed on the above database. Do not include any Markdown formatting or code blocks in your response. Provide only the plain SQL query.

User request: {user_input}
SQL Query:
"""

    # Send the prompt to the Llama model via Groq
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "system", "content": prompt}]
    )

    # Extract and clean the SQL query from the response
    raw_sql = response.choices[0].message.content.strip()
    sql_query = clean_sql_query(raw_sql)
    
    return sql_query

# Function to validate the generated SQL query without executing it
def validate_sql(sql_query, conn):
    try:
        cursor = conn.cursor()
        # Use EXPLAIN QUERY PLAN to validate syntax and references
        cursor.execute("EXPLAIN QUERY PLAN " + sql_query)
        return True, ""
    except sqlite3.Error as e:
        return False, str(e)

# Function to execute the SQL query and fetch results
def execute_query(sql_query, conn):
    is_valid, error_message = validate_sql(sql_query, conn)
    if not is_valid:
        return f"Invalid SQL Query: {error_message}"

    try:
        cursor = conn.cursor()
        cursor.execute(sql_query)
        # Determine if the query is a SELECT statement
        if sql_query.strip().upper().startswith("SELECT"):
            rows = cursor.fetchall()
            # Convert rows to a list of dictionaries for better display
            result = [dict(row) for row in rows]
            return result
        else:
            conn.commit()
            return "Query executed successfully."
    except sqlite3.Error as e:
        return f"SQL execution error: {e}"

# Initialize chat history in Streamlit session state if not already present
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# Streamlit UI Title
st.title("💻 Text2SQL Chatbot")

# Display chat history
for message in st.session_state.chat_history:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Input field for user's message
user_prompt = st.chat_input("Ask LLAMA...")

if user_prompt:
    # Display and store the user's message
    st.chat_message("user").markdown(user_prompt)
    st.session_state.chat_history.append({"role": "user", "content": user_prompt})

    # Convert the user's message into an SQL query
    sql_query = text_to_sql(user_prompt, conn)

    # Display the generated SQL query
    st.chat_message("assistant").markdown(f"**Generated SQL Query:** `{sql_query}`")
    st.session_state.chat_history.append({"role": "assistant", "content": f"**Generated SQL Query:** `{sql_query}`"})

    # Execute the SQL query
    query_result = execute_query(sql_query, conn)

    # Display the SQL execution result
    if isinstance(query_result, list):
        if query_result:
            st.chat_message("assistant").markdown("**Query Result:**")
            st.table(query_result)
        else:
            st.chat_message("assistant").markdown("**Query Result:** No records found.")
    else:
        st.chat_message("assistant").markdown(f"**Query Result:** {query_result}")
    st.session_state.chat_history.append({"role": "assistant", "content": f"**Query Result:** {query_result}"})
