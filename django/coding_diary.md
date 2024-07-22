3. Local postgreSql setup:
  - sudo systemctl start postgresql
  - sudo -i -u postgres
  - CREATE DATABASE industryanalyser;
  - CREATE USER master WITH ENCRYPTED PASSWORD 'password';
  - GRANT ALL PRIVILEGES ON DATABASE industryanalyser TO master
2. http://127.0.0.1:8000/accounts/ outputs "Hello World!"
1. http://127.0.0.1:8000/fetcher/ outputs "Hello World!"