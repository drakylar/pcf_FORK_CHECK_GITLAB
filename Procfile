release: echo 'DELETE_ALL' | python new_initiation.py;
web: if [ ! -f ./configuration/database.sqlite3 ]; then echo 'DELETE_ALL' | python new_initiation.py; fi; python app.py