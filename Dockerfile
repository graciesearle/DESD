# Note: If you are to add anything keep this logic in mind: keep the commands that are less likely to change at the start so we can benefit from the caching layer.

FROM python:3.12-slim

# Set Environment Variables where:
    # PYTHONDONTWRITEBYTECODE: Prevents Python from writing pyc files to disc
    # PYTHONUNBUFFERED: Prevents Python from buffering stdout and stderr (so everything prints immediately (i.e logs))
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install PostgreSQL client dev libraries (apt-get update gets the latest available version, installs build-essential (core tools to compile software) and libpq-dev(so python can talk to postgre) (psycopg2 needs it))
# rm -rf /var/lib/apt/lists/* deletes package index file that were downloaded (decreases image size)
RUN apt-get update && apt-get install -y build-essential libpq-dev && rm -rf /var/lib/apt/lists/*

# Set Work Directory
WORKDIR /app

# Install Dependencies from requirements.txt 
COPY requirements.txt /app/
RUN pip install -r requirements.txt

# Copy Project source code to app directory
COPY . /app/
