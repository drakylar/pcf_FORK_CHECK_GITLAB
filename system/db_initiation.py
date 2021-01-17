import os
import logging

import sqlite3
import psycopg2

from system.crypto_functions import random_string

import system.config_load

db_config = system.config_load.config_dict()['database']
try:
    db_path = system.config_load.config_dict()['database']['path']
except Exception as e:
    logging.error(e)
    logging.info(system.config_load.config_dict())


def create_db():
    if os.path.isfile(db_path):
        new_db_path = db_path + '.' + random_string() + '.old'
        os.rename(db_path, new_db_path)
        logging.info('Moved old db from {} to {}'.format(db_path, new_db_path))

    try:
        if db_config['type'] == 'postgres':
            conn = psycopg2.connect(dbname=db_config['name'], user=db_config['login'],
                                    password=db_config['password'], host=db_config['host'], port=db_config['port'])
        elif db_config['type'] == 'sqlite3':
            conn = sqlite3.connect(db_path)
    except Exception as e:
        # logging.error(e)
        print(e)
        return

    cursor = conn.cursor()

    # create table - Users
    try:
        cursor.execute('''CREATE TABLE Users
                         (
                         id text PRIMARY KEY,
                         fname text default '',
                         lname text default '',
                         email text unique,
                         company text default '',
                         password text
                          );''')
    except:
        print('Error with creating table Users')

    # create table - Teams
    try:
        cursor.execute('''CREATE TABLE Teams
                         (
                         id text PRIMARY KEY,
                         admin_id text, 
                         name text default '',
                         description text default '',
                         users text default '{}',
                         projects text default '',
                         admin_email text default ''
                          );''')
    except:
        print('Error with creating table Teams')


    # create table - Logs
    try:
        cursor.execute('''CREATE TABLE Logs
                             (
                             id text PRIMARY KEY,
                             teams text default '', 
                             description text default '',
                             date integer,
                             user_id text,
                             project text default ''
                              )''')
    except:
        print('Error with creating table Logs')

    # create table - Projects
    try:
        cursor.execute('''CREATE TABLE Projects
                                 (
                                 id text PRIMARY KEY,
                                 name text default '', 
                                 description text default '',
                                 type text default 'pentest',
                                 scope text default '',
                                 start_date int,
                                 end_date int,
                                 auto_archive int default 0,
                                 status int default 1,
                                 testers text DEFAULT '',
                                 teams  text DEFAULT '',
                                 admin_id text
                                  )''')
    except:
        print('Error with creating table Projects')

    # create table - Hosts
    try:
        cursor.execute('''CREATE TABLE Hosts
                                     (
                                     id text PRIMARY KEY,
                                     project_id text, 
                                     ip text,
                                     comment text default '',
                                     user_id text,
                                     threats text default '',
                                     os text default ''
                                     )''')
    except:
        print('Error with creating table Hosts')

    # create table - Hostnames
    try:
        cursor.execute('''CREATE TABLE Hostnames
                                         (
                                         id text PRIMARY KEY,
                                         host_id text, 
                                         hostname text,
                                         description text default '',
                                         user_id text
                                          )''')
    except:
        print('Error with creating table Hostnames')

    # create table - PoC
    try:
        cursor.execute('''CREATE TABLE PoC
                                                 (
                                                 id text PRIMARY KEY,
                                                 port_id text default '',
                                                 description text default '',
                                                 type text default '',
                                                 filename text default '',
                                                 issue_id text,
                                                 user_id text,
                                                 hostname_id text default '0',
                                                 priority integer default 0
                                                  )''')
    except:
        print('Error with creating table PoC')

    # create table - Ports
    try:
        cursor.execute('''CREATE TABLE Ports
                                                     (
                                                     id text PRIMARY KEY,
                                                     host_id text ,
                                                     port integer ,
                                                     is_tcp integer default 1,
                                                     service text default 'other',
                                                     description text default '',
                                                     user_id text,
                                                     project_id text
                                                      )''')
    except:
        print('Error with creating table Ports')

    # create table - Issues
    try:
        cursor.execute('''CREATE TABLE Issues
                                                     (
                                                     id text PRIMARY KEY,
                                                     name text default '',
                                                     description text default '',
                                                     url_path text default '',
                                                     cvss float default 0,
                                                     cwe int default 0,
                                                     cve text default '',
                                                     user_id text not null ,
                                                     services text default '{}',
                                                     status text default '',
                                                     project_id text not null,
                                                     type text default 'custom',
                                                     fix text default '',
                                                     param text default ''
                                                      )''')
    except:
        print('Error with creating table Issues')

    # create table - Networks
    try:
        cursor.execute('''CREATE TABLE Networks
                                                         (
                                                         id text PRIMARY KEY,
                                                         ip text ,
                                                         mask int,
                                                         comment text default '',
                                                         project_id text,
                                                         user_id text,
                                                         is_ipv6 int default 0,
                                                         asn int default 0,
                                                         access_from text default '{}',
                                                         internal_ip text default '',
                                                         cmd text default ''
                                                          )''')
    except:
        print('Error with creating table Networks')

    # create table - Files
    try:
        cursor.execute('''CREATE TABLE Files
                                                             (
                                                             id text PRIMARY KEY,
                                                             project_id text ,
                                                             filename text default '',
                                                             description text default '',
                                                             services text default '{}',
                                                             type text default 'binary',
                                                             user_id text
                                                              )''')
    except:
        print('Error with creating table Files')

    # create table - Credentials
    try:
        cursor.execute('''CREATE TABLE Credentials
                                                 (
                                                 id text PRIMARY KEY,
                                                 login text default '',
                                                 hash text default '',
                                                 hash_type text default '',
                                                 cleartext text default '',
                                                 description text default '',
                                                 source text default '',
                                                 services text default '{}',
                                                 user_id text,
                                                 project_id text 
                                                  )''')
    except:
        print('Error with creating table Credentials')

    # create table - Notes
    try:
        cursor.execute('''CREATE TABLE Notes
                                             (
                                             id text PRIMARY KEY,
                                             project_id text,
                                             name text default '',
                                             text text default '',
                                             user_id text
                                              )''')
    except:
        print('Error with creating table Notes')

    # create table - Chats
    try:
        cursor.execute('''CREATE TABLE Chats
                                             (
                                             id text PRIMARY KEY,
                                             project_id text,
                                             name text default '',
                                             user_id text
                                              )''')
    except:
        print('Error with creating table Chats')

    # create table - Messages
    try:
        cursor.execute('''CREATE TABLE Messages
                                                 (
                                                 id text PRIMARY KEY,
                                                 chat_id text,
                                                 message text default '',
                                                 user_id text,
                                                 time int
                                                  )''')
    except:
        print('Error with creating table Messages')

    # create table - tool_sniffer_http_info
    try:
        cursor.execute('''CREATE TABLE tool_sniffer_http_info
                                                     (
                                                     id text PRIMARY KEY,
                                                     project_id text,
                                                     name text default '',
                                                     status int default 200,
                                                     location text default '',
                                                     body text default ''
                                                      )''')
    except:
        print('Error with creating table tool_sniffer_http_info')

    # create table - tool_sniffer_http_data
    try:
        cursor.execute('''CREATE TABLE tool_sniffer_http_data
                                                             (
                                                             id text PRIMARY KEY,
                                                             sniffer_id text,
                                                             date int,
                                                             ip text default '',
                                                             request text default ''
                                                              )''')
    except:
        print('Error with creating table tool_sniffer_http_data')

    # create table - Configs
    try:
        cursor.execute('''CREATE TABLE Configs
                                             (
                                             id text PRIMARY KEY,
                                             team_id text default '0',
                                             user_id text default '0',
                                             name text default '',
                                             display_name text default '',
                                             data text default '',
                                             visible int default 0
                                             )''')
    except:
        print('Error with creating table configs')

    # create table - ReportTemplates
    try:
        cursor.execute('''CREATE TABLE ReportTemplates
                                                     (
                                                     id text PRIMARY KEY,
                                                     team_id text default '0',
                                                     user_id text default '0',
                                                     name text default '',
                                                     filename text default ''
                                                      )''')
    except:
        print('Error with creating table ReportTemplates')

    # create table - Tokens
    try:
        cursor.execute('''CREATE TABLE Tokens
                                             (
                                             id text PRIMARY KEY,
                                             user_id text default '0',
                                             name text default '',
                                             create_date int default 0,
                                             duration int default 0
                                              )''')
    except:
        print('Error with creating table Tokens')

    conn.commit()
