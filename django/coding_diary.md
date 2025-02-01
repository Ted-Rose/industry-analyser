6. Startup command on Windows terminal
 - `python projects\industry-analyser\django\manage.py runserver`
5. Won't deploy on pythonanywhere as its proxy is blocking requests to portals
4. Issues with venv creation on pythonanywhere. This path worked:
  1. `python3.10 -m venv venv`
  2. `source venv/bin/activate`
  3. `pip install -r requirements.txt`
3. Local postgresql setup:
  - sudo systemctl start postgresql
  - sudo -i -u postgres
  - CREATE DATABASE industryanalyser
  - CREATE USER postgresql  WITH ENCRYPTED PASSWORD 'password';
  - GRANT ALL PRIVILEGES ON DATABASE industryanalyser TO postgresql;
  - ALTER DATABASE industryanalyser OWNER TO postgresql;
2. http://127.0.0.1:8000/accounts/ outputs "Hello World!"
1. http://127.0.0.1:8000/fetcher/ outputs "Hello World!"