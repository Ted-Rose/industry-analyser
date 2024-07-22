3. Local postgresql setup:
  - sudo systemctl start postgresql
  - sudo -i -u postgres
  - CREATE DATABASE industryanalyser
  - CREATE USER postgresql  WITH ENCRYPTED PASSWORD 'password';
  - GRANT ALL PRIVILEGES ON DATABASE industryanalyser TO postgresql;
  - ALTER DATABASE industryanalyser OWNER TO postgresql;
2. http://127.0.0.1:8000/accounts/ outputs "Hello World!"
1. http://127.0.0.1:8000/fetcher/ outputs "Hello World!"