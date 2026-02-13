# DESD
Distributed Entriprise System Development Group Project.

To install Django:
1. Create venv:
    - On Windows: 
        ```
        python -m venv venv  
        ```
    - On Mac:
        ```
        python3 -m venv venv
        ```
    
2. Activate venv:
    - On Windows:
        ```
        venv\Scripts\activate
        ```
    - On Mac
        ```
        source venv/bin/activate
        ```
3. Run ``` pip install -r requirements.txt ```

To install Docker
1. Very straightforward just go to your search engine and download it from the official Docker website: https://www.docker.com/products/docker-desktop/

To install PostGreSQL
1. Download pgAdmin4 from https://www.pgadmin.org/download/
2. Go to Docker -> Images -> Terminal -> docker pull postgres or Myhub (Search postgres and download)
3. Open Docker Terminal and adjust settings docker to your liking.

``` bash
run --name some-postgres -p 5433:5432 -e POSTGRES_PASSWORD=mysecretpassword -d postgres
```
*Note: -p : is your ports, keep 5432 the same, -d is the database name.*

4. Through pgAdmin4 add the details you chose and connect.
