#!/bin/bash

#Setup script

#This script resets and initialises the entire local Docker environment.
#It will:
#    1. COMPLETELY WIPE all existing Docker volumes (database and media files)
#    2. Build fresh Docker images.
#    3. Start the services (web, db)
#    4. Wait for the database to be ready.
#    5. Apply all the database migrations.
#    6. Run the `create_demo_data` command to seed the database with test data, including a default superuser

#Why:
#    This was created so that only one command needs to be run during developement to get up to date from pulling prs, or from main.


# PREREQUISITES:
#   1. Open Docker Desktop -> Settings -> Resources -> WSL Integration -> ensure WSL2 distribution is enabled and ubuntu is enabled.
#   2. Restart Docker Desktop after enabling.

#Usage:
#    ./setup.sh


# Define Project Name explicitly to avoid "hash" names in WSL
PROJECT_NAME="desd"

# Style Definitions
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Safety Check first (-p = show prompt message, -n 1 = read only 1 character, -r= raw input)
echo -e "${YELLOW}WARNING:${NC} This script will permanently delete all local Docker volumes, including the database and media. ONLY RUN THIS IN LOCAL DEVELOPMENT. NOT PRODUCTION."
read -p "Are you sure you want to continue? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]
then
    echo "Setup Cancelled."
    exit 1
fi

# 1. Destroy volumes
echo -e "\n${GREEN}Step 1: Tearing down existing environment and volumes...${NC}"

# Remove all containers
docker rm -f $(docker ps -aq) 2>/dev/null

docker-compose -p $PROJECT_NAME down -v --remove-orphans # --remove-orphans to remove containers that were created but are no longer associated with the docker-compose.yml file

# Remove any dangling containers.
docker container prune -f 

# Remove any dangling networks 
docker network prune -f 

if [ $? -ne 0 ]; then # If exit status is not 0 then fail
    echo -e "${RED}Error: Failed to tear down Docker environment. Aborting.${NC}"
    exit 1
fi 

# 2. Build and Start fresh services.
echo -e "\n${GREEN}Step 2: Building and starting fresh services in the background...${NC}"
docker-compose -p $PROJECT_NAME up --build -d
if [ $? -ne 0 ]; then
    echo -e "${RED}Error: Docker Compose failed to build or start. Check Dockerfile and docker-compose.yml. Aborting.${NC}"
    exit 1
fi 

# 3. Wait for PostgreSQL database
echo -e "\n${GREEN}Step 3: Waiting for the PostgreSQL database to be ready...${NC}"
# we will wait for up to 30 seconds and then abort
retries=15
until docker-compose -p $PROJECT_NAME exec -T db pg_isready -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-bristol_food_db}" -q || [ $retries -eq 0 ]; do
    echo "Waiting for database, $((retries--)) attempts remaining..."
    sleep 2
done 

if [ $retries -eq 0 ]; then
    echo -e "${RED}Error: Database did not become available in time. Check the 'db' service logs. Aborting.${NC}"
    docker-compose logs db
    exit 1
fi
echo "Database is ready!"

# 4. Run Backend setup commands
echo -e "\n${GREEN}Step 4: Running database migrations...${NC}"
docker-compose -p $PROJECT_NAME exec web python manage.py migrate
if [ $? -ne 0 ]; then
    echo -e "${RED}Error: Migrations failed. Aborting.${NC}"
    exit 1
fi

echo -e "\n${GREEN}Step 5: Seeding the database with demo data...${NC}"
docker-compose -p $PROJECT_NAME exec web python manage.py create_demo_data
if [ $? -ne 0 ]; then
    echo -e "${RED}Error: Data seeding failed. Aborting.${NC}"
    exit 1
fi

# 5. Confirmation
echo -e "\n--------------------------------------------------"
echo -e "${GREEN}SUCCESS: Local environment is ready!${NC}"
echo "--------------------------------------------------"
echo -e "You can access the site at: ${YELLOW}http://localhost:8000${NC}"
echo -e "Admin panel: ${YELLOW}http://localhost:8000/admin${NC}"
echo ""
echo "Superuser credentials:"
echo -e "  - Email:    ${YELLOW}root@gmail.com${NC}"
echo -e "  - Password: ${YELLOW}Root1212$ ${NC}"
echo ""
echo "Running containers:"
docker-compose ps
echo "--------------------------------------------------"
